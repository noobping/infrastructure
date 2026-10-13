#!/usr/bin/env python3
"""Offline safety contracts, credential persistence and executable backup hooks."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROLE = Path(__file__).resolve().parents[1]
REPO = ROLE.parents[1]
STUB = r'''#!/usr/bin/env python3
import os, subprocess, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
args = sys.argv[1:]
failure = os.environ.get('FAIL', '')
with (root/'calls').open('a') as log:
    log.write(Path(sys.argv[0]).name + ' ' + ' '.join(args) + '\n')
if Path(sys.argv[0]).name == 'systemctl':
    sys.exit(0)
if args[:2] == ['volume', 'exists']:
    sys.exit(0 if failure == 'existing' else 1)
if args[:2] == ['volume', 'inspect']:
    print('local' if failure == 'nfs' else 'nfs')
elif 'pg_dump' in args:
    if failure == 'dump': sys.exit(1)
    print('PGDMP fixture')
elif 'pg_restore' in args:
    data = sys.stdin.read()
    sys.exit(1 if failure == 'verify' or not data.startswith('PGDMP') else 0)
elif args[0] == 'run':
    if failure == 'transfer': sys.exit(1)
    body = args[-1].replace('/backups', str(root/'export'))
    sys.exit(subprocess.run(['/bin/sh', '-eu', '-c', body]).returncode)
else:
    raise RuntimeError(args)
'''


def module(path):
    loader = importlib.machinery.SourceFileLoader(path.name.replace('-', '_'), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


class Hooks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        (self.root/'export').mkdir()
        self.credentials = self.root/'credentials'
        self.state = self.root/'backup'
        for name in ['podman', 'systemctl']:
            p = self.bin/name
            p.write_text(STUB)
            p.chmod(0o755)
        for name in ['audiomuse-prepare', 'audiomuse-backup']:
            script = (ROLE/'bin'/name).read_text()
            script = script.replace('/var/lib/infrastructure/backup/audiomuse', str(self.state))
            script = script.replace('/var/lib/audiomuse', str(self.credentials))
            script = script.replace('/etc/containers/systemd/audiomuse-web.container', str(ROLE/'containers/audiomuse-web.container'))
            script = script.replace('-o root -g root', f'-o {os.getuid()} -g {os.getgid()}')
            p = self.bin/name
            p.write_text(script)
            p.chmod(0o755)
        self.env = {**os.environ, 'FIXTURE_ROOT': str(self.root), 'PATH': f'{self.bin}:{os.environ["PATH"]}'}

    def run_hook(self, name, *args, failure='', success=True):
        result = subprocess.run([str(self.bin/name), *args], env={**self.env, 'FAIL':failure},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def prepare_credentials(self):
        self.run_hook('audiomuse-prepare')
        (self.credentials/'jellyfin.env').write_text('JELLYFIN_TOKEN=fixture-secret\n')

    def test_credentials_persist_and_missing_half_is_rejected(self):
        result = self.run_hook('audiomuse-prepare')
        values = {p.name:p.read_bytes() for p in self.credentials.glob('*.env')}
        self.run_hook('audiomuse-prepare')
        self.assertEqual(values, {p.name:p.read_bytes() for p in self.credentials.glob('*.env')})
        for p in self.credentials.glob('*.env'):
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(p.read_text(), result.stdout + result.stderr)
        (self.credentials/'auth.env').unlink()
        self.run_hook('audiomuse-prepare', success=False)
        self.assertEqual(values['database.env'], (self.credentials/'database.env').read_bytes())

    def test_existing_database_never_gets_a_new_password(self):
        self.run_hook('audiomuse-prepare', failure='existing', success=False)
        self.assertFalse((self.credentials/'database.env').exists())

    def test_online_backup_contains_database_and_secrets_and_holds_until_finish(self):
        self.prepare_credentials()
        self.run_hook('audiomuse-backup', 'prepare')
        self.assertTrue((self.state/'prepared').exists())
        bundle = self.root/'export/audiomuse.tar'
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
        with tarfile.open(bundle) as archive:
            self.assertEqual(set(archive.getnames()), {'audiomuse.dump','database.env','auth.env','jellyfin.env'})
            self.assertTrue(archive.extractfile('audiomuse.dump').read().startswith(b'PGDMP'))
        self.assertNotIn('systemctl stop', (self.root/'calls').read_text())
        self.run_hook('audiomuse-backup', 'finish')
        self.assertFalse((self.state/'prepared').exists())
        self.run_hook('audiomuse-backup', 'finish')

    def test_dump_nfs_or_transfer_failure_preserves_previous_backup_and_hold(self):
        self.prepare_credentials()
        bundle = self.root/'export/audiomuse.tar'
        bundle.write_bytes(b'previous')
        for failure in ['dump', 'verify', 'nfs', 'transfer']:
            with self.subTest(failure=failure):
                self.run_hook('audiomuse-backup', 'prepare', failure=failure, success=False)
                self.assertTrue((self.state/'prepared').exists())
                self.assertEqual(bundle.read_bytes(), b'previous')
                self.assertFalse(list(self.state.glob('.dump.*')))

    def test_backup_lock(self):
        self.prepare_credentials()
        self.state.mkdir()
        with (self.state/'lock').open('w') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.run_hook('audiomuse-backup', 'prepare', success=False)


class Contracts(unittest.TestCase):
    def test_quadlet_generator_and_security(self):
        generator = '/usr/lib/systemd/system-generators/podman-system-generator'
        if Path(generator).exists():
            result = subprocess.run([generator, '--dryrun'], env={**os.environ, 'QUADLET_UNIT_DIRS':str(ROLE/'containers')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('unsupported key', result.stderr)
            for role in ['web','worker','database']:
                self.assertIn(f'audiomuse-{role}.service', result.stdout)
        for role in ['web','worker','database']:
            data = (ROLE/f'containers/audiomuse-{role}.container').read_text()
            self.assertRegex(data, r'Image=\S+:\d[^\s]+@sha256:[0-9a-f]{64}')
            for required in ['ReadOnly=true', 'DropCapability=all', 'NoNewPrivileges=true', 'MemoryMax=', 'CPUQuota=', 'HealthCmd=']:
                self.assertIn(required, data)
            self.assertNotIn('SecurityLabelDisable', data)
            self.assertNotIn('Network=host', data)
            self.assertNotIn('/music', data)
            if role != 'web': self.assertNotIn('PublishPort=', data)
        pg = (ROLE/'containers/audiomuse-postgres.volume').read_text()
        self.assertNotIn('nfs', pg)
        self.assertIn('After=audiomuse-prepare.service', pg)
        backup = (ROLE/'containers/audiomuse-backups.volume').read_text()
        self.assertIn('Type=nfs', backup)
        self.assertIn(',hard,', backup)

    def test_jellyfin_plugin_abi_matches_pin_and_nas_remains_unchanged(self):
        lock = json.loads((ROLE.parent/'jellyfin/audiomuse-plugin.lock.json').read_text())
        jellyfin = (ROLE.parent/'jellyfin/containers/jellyfin.container').read_text()
        self.assertIn(':'+lock['jellyfin_version']+'@sha256:', jellyfin)
        self.assertEqual(lock['target_abi'], '10.11.0.0')
        installer = module(ROLE.parent/'jellyfin/install-audiomuse-plugin')
        with self.assertRaises(ValueError): installer.verified_archive(b'bad download', lock)
        # Added role has no Jellyfin config/media mounts or legacy-writer side effects.
        inventory = json.loads((REPO/'vms/inventory.json').read_text())
        role = next(v for v in inventory['vms'] if v['name'] == 'audiomuse')
        self.assertFalse(role['autostart'])
        self.assertEqual(role['on_demand']['legacy_services'], [])
        # Never reuse the NAS videos/photos/media identities for backup secrets.
        nas_uids = set(re.findall(r'uid: (\d+)', (REPO/'butane/nas.yml').read_text()))
        self.assertNotIn('1009', nas_uids)
        self.assertGreaterEqual(role['memory_mib'], 8192)
        self.assertEqual(role['on_demand']['idle_seconds'], 1800)

    def test_configuration_guard_rejects_world_readable_and_placeholders(self):
        guard = module(ROLE/'bin/audiomuse-config-check')
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'jellyfin.env'
            p.write_text('JELLYFIN_URL=http://nas.vm:8096\nJELLYFIN_USER_ID=fixture\nJELLYFIN_TOKEN=fixture\n')
            p.chmod(0o644)
            with self.assertRaises(ValueError): guard.validate(p)
            p.chmod(0o600)
            real = p.lstat()
            with patch.object(Path, 'lstat', return_value=type('Info', (), {'st_mode':real.st_mode, 'st_uid':0})()):
                guard.validate(p)
                p.write_text(p.read_text().replace('JELLYFIN_TOKEN=fixture', 'JELLYFIN_TOKEN=your_token'))
                with self.assertRaises(ValueError): guard.validate(p)
                p.write_text('JELLYFIN_URL=http://your_jellyfin_server\nJELLYFIN_USER_ID=fixture\nJELLYFIN_TOKEN=fixture\n')
                with self.assertRaises(ValueError): guard.validate(p)


if __name__ == '__main__':
    unittest.main()
