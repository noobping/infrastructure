#!/usr/bin/env python3
"""Exercise credential persistence and backup recovery without a running VM."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROLE = Path(__file__).resolve().parents[1]
STUB = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
state_path = root / 'state.json'
state = json.loads(state_path.read_text())
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with (root / 'calls').open('a') as log:
    log.write(name + ' ' + ' '.join(args) + '\n')
failure = os.environ.get('FAIL', '')
def save():
    state_path.write_text(json.dumps(state))
if name == 'systemctl':
    if args[0] == 'is-active':
        sys.exit(0 if args[-1] == 'immich-database.service' or state['active'] else 3)
    if args[0] == 'stop':
        if failure == 'stop': sys.exit(1)
        state['active'] = False
        save()
    if args[0] == 'start':
        if failure == 'start': sys.exit(1)
        state['active'] = True
        save()
elif name == 'podman':
    if 'pg_dump' in args:
        if failure == 'dump': sys.exit(1)
        sys.stdout.write('PGDMP fixture archive')
    elif 'pg_restore' in args:
        data = sys.stdin.read()
        sys.exit(1 if failure == 'verify' or not data.startswith('PGDMP') else 0)
    elif args[0] == 'volume':
        print('local' if failure == 'nfs' else 'nfs')
    elif args[0] == 'run':
        if failure == 'transfer': sys.exit(125)
        # Execute the real atomic-copy shell body in an isolated stand-in mount.
        body = args[-1].replace('/data', str(root / 'media'))
        sys.exit(subprocess.run(['/bin/sh', '-eu', '-c', body]).returncode)
    else:
        raise RuntimeError(args)
else:
    raise RuntimeError(name)
'''


class Hooks(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='immich-hooks-')
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.root / 'state.json').write_text(json.dumps({'active': True}))
        for name in ['systemctl', 'podman']:
            path = self.bin / name
            path.write_text(STUB)
            path.chmod(0o755)
        self.state = self.root / 'backup'
        self.credentials = self.root / 'credentials'
        for name in ['immich-prepare', 'immich-backup']:
            script = (ROLE / 'bin' / name).read_text()
            script = script.replace('/var/lib/infrastructure/backup/immich', str(self.state))
            script = script.replace('/var/lib/immich', str(self.credentials))
            script = script.replace('/etc/containers/systemd/immich-server.container',
                                    str(ROLE / 'containers/immich-server.container'))
            script = script.replace('-o root -g root', f'-o {os.getuid()} -g {os.getgid()}')
            path = self.bin / name
            path.write_text(script)
            path.chmod(0o755)
        self.env = {**os.environ, 'FIXTURE_ROOT': str(self.root),
                    'PATH': f'{self.bin}:{os.environ["PATH"]}'}

    def run_hook(self, name, *args, failure='', success=True):
        result = subprocess.run([str(self.bin / name), *args],
                                env={**self.env, 'FAIL': failure}, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def active(self):
        return json.loads((self.root / 'state.json').read_text())['active']

    def test_password_survives_restarts(self):
        result = self.run_hook('immich-prepare')
        env_file = self.credentials / 'database.env'
        original = env_file.read_text()
        settings = dict(line.split('=', 1) for line in original.splitlines())
        self.assertEqual(len(settings['DB_PASSWORD']), 64)
        self.assertEqual(settings['DB_PASSWORD'], settings['POSTGRES_PASSWORD'])
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(settings['DB_PASSWORD'], result.stdout + result.stderr)
        self.run_hook('immich-prepare')
        self.assertEqual(original, env_file.read_text())
        env_file.write_text('')
        self.run_hook('immich-prepare', success=False)
        self.assertEqual(env_file.read_text(), '')

    def test_prepare_holds_writes_until_finish(self):
        self.run_hook('immich-backup', 'prepare')
        self.assertFalse(self.active())
        self.assertTrue((self.state / 'server-was-active').exists())
        dump = self.root / 'media/backups/infrastructure/immich.dump'
        self.assertTrue(dump.read_text().startswith('PGDMP'))
        self.assertEqual(dump.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.state.glob('.dump.*')))
        self.run_hook('immich-backup', 'finish')
        self.assertTrue(self.active())
        self.assertFalse((self.state / 'server-was-active').exists())
        self.run_hook('immich-backup', 'finish')

    def test_failures_resume_server_and_preserve_previous_dump(self):
        dump = self.root / 'media/backups/infrastructure/immich.dump'
        dump.parent.mkdir(parents=True)
        dump.write_text('previous backup')
        for failure in ['stop', 'dump', 'verify', 'nfs', 'transfer']:
            with self.subTest(failure=failure):
                self.run_hook('immich-backup', 'prepare', failure=failure, success=False)
                self.assertTrue(self.active())
                self.assertFalse((self.state / 'server-was-active').exists())
                self.assertFalse(list(self.state.glob('.dump.*')))
                self.assertEqual(dump.read_text(), 'previous backup')

    def test_finish_can_be_retried(self):
        self.run_hook('immich-backup', 'prepare')
        self.run_hook('immich-backup', 'finish', failure='start', success=False)
        self.assertTrue((self.state / 'server-was-active').exists())
        self.run_hook('immich-backup', 'finish')
        self.assertTrue(self.active())

    def test_inactive_server_is_not_started(self):
        (self.root / 'state.json').write_text(json.dumps({'active': False}))
        self.run_hook('immich-backup', 'prepare')
        self.run_hook('immich-backup', 'finish')
        self.assertFalse(self.active())

    def test_interrupted_prepare_recovers_before_next_backup(self):
        self.run_hook('immich-backup', 'prepare')
        self.run_hook('immich-backup', 'prepare')
        self.assertFalse(self.active())
        self.run_hook('immich-backup', 'finish')
        self.assertTrue(self.active())

    def test_concurrent_backup_is_rejected(self):
        self.state.mkdir()
        with (self.state / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_hook('immich-backup', 'prepare', success=False)
        self.assertTrue(self.active())


if __name__ == '__main__':
    unittest.main()
