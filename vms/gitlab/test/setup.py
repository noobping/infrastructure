#!/usr/bin/python3
"""Local setup regression tests; no SSH, credentials or production services."""
import ctypes
import ctypes.util
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


remote = module('setup_remote', ROOT/'setup-remote.py')
client = module('setup_client', ROOT/'setup.py')


class Setup(unittest.TestCase):
    def test_butane_administrator_is_reused(self):
        self.assertEqual(client.butane_user(), 'nick')

    def test_transport_keeps_password_out_of_arguments_and_requires_host_identity(self):
        with patch.object(client.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')) as run:
            client.remote('gitlab.vm', 'nick', 'fixture-password-do-not-log', {'action': 'worker'})
        args = run.call_args.args[0]
        self.assertNotIn('fixture-password-do-not-log', ' '.join(args))
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('fixture-password-do-not-log', run.call_args.kwargs['input'])

    def test_tool_failures_do_not_print_secret_output(self):
        with patch.object(remote.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='secret', stderr='secret')):
            with self.assertRaisesRegex(RuntimeError, 'cosign failed') as error:
                remote.run('cosign', 'generate-key-pair')
        self.assertNotIn('secret', str(error.exception))

    def test_wrong_vm_password_cannot_change_gitlab_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'.ssh/authorized_keys.d').mkdir(parents=True)
            (home/'.ssh/authorized_keys.d/ignition').write_text('ssh-ed25519 Zml4dHVyZQ== fixture\nfrom="host" ssh-rsa a2V5 restricted\n')
            library = ctypes.CDLL(ctypes.util.find_library('crypt'))
            library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            library.crypt.restype = ctypes.c_char_p
            hashed = library.crypt(b'fixture-password', b'$6$fixture$').decode()
            read = Path.read_text
            def content(path, *a, **kw):
                return 'nick:'+hashed+':1:2:3:4:5:6:7\n' if str(path) == '/etc/shadow' else read(path, *a, **kw)
            with patch.object(remote.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_dir=directory)), \
                 patch.object(Path, 'read_text', content):
                self.assertEqual(remote.vm_identity('nick', 'fixture-password'), ['ssh-ed25519 Zml4dHVyZQ=='])
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    remote.vm_identity('nick', 'wrong-password')

    def test_atomic_credentials_stay_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'private/config'
            remote.write(path, 'first')
            remote.write(path, 'second')
            self.assertEqual(path.read_text(), 'second')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_account_setup_revokes_temporary_token_on_failure(self):
        calls = []
        def api(token, method, path, data=None, **kwargs):
            calls.append((method, path, data))
            if path == '/user': return {'id': 1, 'is_admin': True, 'username': 'root'}
            if path == '/user/keys':
                if method == 'GET': return []
                raise RuntimeError('Fixture key failure')
        with patch.object(remote, 'vm_identity', return_value=['ssh-ed25519 fixture']), \
             patch.object(remote, 'wait_ready'), \
             patch.object(remote, 'trust'), patch.object(remote, 'write'), \
             patch.object(remote, 'api', api), \
             patch.object(remote, 'run', return_value='{"token":"temporary-fixture-token"}') as run:
            with self.assertRaisesRegex(RuntimeError, 'Fixture key failure'):
                remote.server({'username': 'nick', 'password': 'fixture-password', 'certificate': 'fixture'})
        self.assertEqual(calls[-1][:2], ('DELETE', '/personal_access_tokens/self'))
        password_calls = [call for call in run.call_args_list if 'input' in call.kwargs]
        self.assertEqual(len(password_calls), 1)
        self.assertNotIn('fixture-password', ' '.join(password_calls[0].args))
        self.assertEqual(json.loads(password_calls[0].kwargs['input'])['password'], 'fixture-password')
        self.assertNotIn('password', next(d for m, p, d in calls if m == 'PUT' and p == '/users/1'))

    def test_certificate_import_rejects_private_key_and_non_ca(self):
        with self.assertRaises(ValueError): remote.trust('PRIVATE KEY')
        with patch.object(remote, 'run', return_value='CA:FALSE'), patch.object(remote, 'write') as write:
            with self.assertRaises(ValueError): remote.trust('-----BEGIN CERTIFICATE-----\nfixture')
            write.assert_not_called()

    def test_reconfigure_waits_through_unavailable_and_unready_application(self):
        with patch.object(remote, 'run', side_effect=[RuntimeError('restarting'), '{"status":"failed"}', '{"status":"ok"}']) as run, \
             patch.object(remote.time, 'sleep') as sleep:
            remote.wait_ready()
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_project_runner_and_signing_are_idempotent_and_protected(self):
        calls = []
        variables = {}
        project = {'id': 1, 'namespace': {'full_path': 'nick'}, 'visibility': 'private', 'default_branch': 'main'}
        def api(token, method, path, data=None, missing=False):
            calls.append((method, path, data))
            if method == 'GET' and path == '/projects/nick%2Finfrastructure': return project
            if '/variables' in path:
                name = path.rsplit('/', 1)[-1] if method != 'POST' else data['key']
                if method == 'GET': return variables.get(name)
                variables[name] = data
                return data
            if method == 'GET' and path == '/runners/7': return {'projects': [{'id': 1}]}
            if method == 'POST' and path == '/user/runners': return {'id': 7, 'token': 'glrt-fixture'}
            return None
        with tempfile.TemporaryDirectory() as directory, patch.object(remote, 'api', api):
            signing = {'private': 'fixture-private', 'public': 'fixture-public', 'password': 'fixture-password'}
            for _ in range(2):
                result = remote.configure_project('fixture', 'nick', signing, Path(directory))
                self.assertEqual(result['project'], 'nick/infrastructure')
            with self.assertRaisesRegex(ValueError, 'signing identity differs'):
                remote.configure_project('fixture', 'nick', {**signing, 'public': 'wrong-key'}, Path(directory))
        registrations = [d for m, p, d in calls if m == 'POST' and p == '/user/runners']
        self.assertEqual(len(registrations), 1)
        self.assertTrue(registrations[0]['locked'])
        self.assertEqual(registrations[0]['access_level'], 'ref_protected')
        self.assertFalse(registrations[0]['run_untagged'])
        self.assertTrue(all(value['protected'] for value in variables.values()))
        self.assertTrue(variables['COSIGN_PASSWORD']['masked'])
        self.assertEqual(variables['COSIGN_KEY']['variable_type'], 'file')
        self.assertFalse(any('/import' in p for _, p, _ in calls))

    def test_frontend_preserves_cockpit_ssh_jellyfin_and_has_no_cluster_dependency(self):
        repo = ROOT.parents[1]
        unit = (repo/'vms/gitlab/containers/gitlab-frontend.container').read_text()
        caddy = (repo/'vms/gitlab/frontend/Caddyfile').read_text()
        self.assertEqual([line for line in unit.splitlines() if line.startswith('PublishPort=')],
                         [])
        self.assertIn('Network=host', unit)
        for setting in ('User=65532:65532', 'DropCapability=all', 'NoNewPrivileges=true', 'ReadOnly=true',
                        'MemoryMax=256M', 'RequiresMountsFor=/var/lib/gitlab/frontend'):
            self.assertIn(setting, unit)
        self.assertIn('auto_https disable_redirects', caddy)
        self.assertIn('admin off', caddy)
        self.assertNotIn('k3s.vm', caddy+unit+(ROOT/'setup.py').read_text())
        self.assertNotIn('health_uri', caddy)
        self.assertIn('Exec=--port 443', (repo/'images/nas/containers/cockpit.container').read_text())
        jellyfin = (repo/'images/nas/containers/jellyfin.container').read_text()
        self.assertIn('-p 8096:8096 -p 8920:8920', jellyfin)
        self.assertIn('/var/lib/containers/jellyfin:/config', jellyfin)
        self.assertNotIn('jellyfin', unit+caddy)
        self.assertIn('- name: sshd.service\n      enabled: true', (repo/'butane/nas.yml').read_text())
        self.assertIn("external_url 'https://git.vm:8443'", (ROOT/'gitlab.rb').read_text())
        self.assertIn("registry_external_url 'https://git-registry.vm:8443'", (ROOT/'gitlab.rb').read_text())
        self.assertIn('url = "https://gitlab.vm:8443"', (repo/'vms/gitlab-runner/config.toml').read_text())

    def test_nas_setup_only_activates_gitlab_and_preserves_existing_hold(self):
        for held in (False, True):
            with patch.object(remote, 'run', return_value='') as run, \
                 patch.object(remote, 'write') as write, \
                 patch.object(Path, 'exists', return_value=held), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch.object(Path, 'read_text', return_value='fixture-ca'):
                result = remote.nas({'inventory': {'vms': []}})
            self.assertEqual(result, {'prior_hold': held})
            self.assertEqual([c.args for c in run.call_args_list if c.args[0] == 'systemctl'],
                             [])
            self.assertTrue(all(c.args[2] == 'gitlab' for c in run.call_args_list if c.args[0] == 'vm-on-demand'))
            self.assertFalse(any(c.args[0] == 'podman' for c in run.call_args_list))
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[0], '/run/gitlab-setup-inventory.json')

    def test_certificate_is_read_only_from_vm_state(self):
        with patch.object(remote, 'run', return_value='') as run, \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'read_text', return_value='fixture-ca'):
            self.assertEqual(remote.certificate(), {'certificate': 'fixture-ca'})
        self.assertEqual(run.call_args_list[0].args, ('systemctl', 'start', 'gitlab-frontend.service'))
        self.assertNotIn('nas.vm', str(run.call_args_list))
        repo = ROOT.parents[1]
        self.assertFalse((repo/'images/nas/containers/gitlab-frontend.container').exists())
        self.assertNotIn('gitlab-frontend', (repo/'images/nas/Containerfile').read_text())
        backup = (repo/'vms/vm/bin/gitlab-backup').read_text()
        self.assertIn('cp -a /var/lib/gitlab/frontend "$staging/frontend"', backup)
        self.assertNotIn('/var/srv/ssd', (ROOT/'frontend/prepare').read_text())


if __name__ == '__main__': unittest.main()
