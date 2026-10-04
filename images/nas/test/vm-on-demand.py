#!/usr/bin/env python3
"""Exercise shutdown decisions, races, guest reports and real UDP forwarding."""
import base64
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import threading
import time
import sys

sys.dont_write_bytecode = True
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO/path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


host = module('demand', 'images/nas/bin/vm-on-demand')
guest = module('probe', 'vms/vm/bin/vm-idle-check')
udp = module('udp', 'images/nas/vm-on-demand/udp-proxy')


class Host(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('RUNTIME', 'STATE', 'CONFIG', 'UNITS'):
            path = self.root/name
            path.mkdir()
            patcher = patch.object(host, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = host.validate_inventory(REPO/'vms/inventory.json', ['immich'])[0]
        for name, value in [('enabled', True), ('state', 'running'), ('proxy_busy', False),
                            ('guest_idle', True), ('property_of', 'inactive')]:
            patcher = patch.object(host, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(host, 'shutdown')
        self.shutdown = patcher.start()
        self.addCleanup(patcher.stop)
        self.activity = host.RUNTIME/'immich.activity'
        self.activity.write_text(str(time.monotonic()-1900))
        (host.RUNTIME/'immich.confirmed-idle').touch()

    def test_only_confirmed_idle_vm_shuts_down(self):
        host.idle_one(self.config)
        self.shutdown.assert_called_once_with(self.config)

    def test_busy_application_restarts_full_idle_period(self):
        self.guest_idle.return_value = False
        host.idle_one(self.config)
        self.shutdown.assert_not_called()
        self.assertLess(time.monotonic()-float(self.activity.read_text()), 1)
        self.guest_idle.return_value = True
        host.idle_one(self.config)
        self.shutdown.assert_not_called()

    def test_first_positive_report_starts_full_idle_interval(self):
        (host.RUNTIME/'immich.confirmed-idle').unlink()
        host.idle_one(self.config)
        self.shutdown.assert_not_called()
        self.assertLess(time.monotonic()-float(self.activity.read_text()), 1)
        self.assertTrue((host.RUNTIME/'immich.confirmed-idle').exists())

    def test_manual_hold_survives_controller_restart(self):
        (host.STATE/'immich.hold').touch()
        host.idle_one(self.config)
        self.shutdown.assert_not_called()
        self.guest_idle.assert_not_called()

    def test_new_connection_during_probe_cancels_shutdown(self):
        self.proxy_busy.side_effect = [False, True]
        host.idle_one(self.config)
        self.shutdown.assert_not_called()

    def test_backup_and_client_traffic_prevent_shutdown(self):
        for proxy, backup in [(True, 'inactive'), (False, 'active'), (False, 'activating')]:
            self.proxy_busy.return_value = proxy
            self.property_of.return_value = backup
            host.idle_one(self.config)
        self.shutdown.assert_not_called()

    def test_off_disabled_or_paused_guest_is_never_started_by_idle_check(self):
        for enabled, state in [(False, 'running'), (True, 'shut off'), (True, 'paused')]:
            self.enabled.return_value, self.state.return_value = enabled, state
            host.idle_one(self.config)
        self.shutdown.assert_not_called()
        self.guest_idle.assert_not_called()

    def test_missing_activity_after_host_boot_gets_full_grace_period(self):
        self.activity.unlink()
        host.idle_one(self.config)
        self.shutdown.assert_not_called()
        self.guest_idle.assert_not_called()

    def test_qga_error_is_not_idle(self):
        (host.CONFIG/'immich.json').write_text(json.dumps(self.config))
        self.guest_idle.side_effect = ValueError('broken guest agent')
        with patch.object(host.os, 'geteuid', return_value=0), patch('sys.argv', ['vm-on-demand', 'idle']):
            host.main()
        self.shutdown.assert_not_called()
        self.assertLess(time.monotonic()-float(self.activity.read_text()), 1)

    def test_current_k3s_policy_unchanged_and_cannot_be_enabled(self):
        inventory = json.loads((REPO/'vms/inventory.json').read_text())
        k3s = next(vm for vm in inventory['vms'] if vm['name'] == 'k3s')
        self.assertIs(k3s['autostart'], True)
        self.assertNotIn('on_demand', k3s)
        with self.assertRaises(ValueError):
            host.validate_inventory(REPO/'vms/inventory.json', ['k3s'])
        configs = host.validate_inventory(REPO/'vms/inventory.json', [])
        self.assertEqual({c['name'] for c in configs}, {'minecraft', 'immich', 'jellyfin'})

    def test_unsafe_inventory_rejected_before_rendering(self):
        inventory = json.loads((REPO/'vms/inventory.json').read_text())
        minecraft = inventory['vms'][1]
        for key, value in [('hostname', 'host;evil'), ('autostart', True)]:
            data = json.loads(json.dumps(inventory))
            data['vms'][1][key] = value
            path = self.root/'inventory.json'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                host.validate_inventory(path, [])
        minecraft['on_demand']['endpoints'][1]['listen_port'] = 19133
        path.write_text(json.dumps(inventory))
        with self.assertRaises(ValueError):
            host.validate_inventory(path, [])

    def test_legacy_writer_must_be_masked_and_inactive(self):
        config = host.validate_inventory(REPO/'vms/inventory.json', ['jellyfin'])[0]
        for states in [('loaded', 'active'), ('loaded', 'inactive', 'enabled'),
                       ('loaded', 'inactive', 'masked-runtime')]:
            self.property_of.side_effect = states
            with self.assertRaises(RuntimeError):
                host.guard_legacy(config)
        self.property_of.side_effect = ['masked', 'inactive', 'masked']
        host.guard_legacy(config)

    def test_wake_serializes_concurrent_requests(self):
        self.state.return_value = 'shut off'
        starts = []
        def fake_virsh(*args):
            if args[0] == 'start':
                starts.append(args[1])
                time.sleep(0.03)
                self.state.return_value = 'running'
        def wake():
            with host.locked('immich'):
                host.start(self.config)
        with patch.object(host, 'virsh', side_effect=fake_virsh):
            threads = [threading.Thread(target=wake) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
        self.assertEqual(starts, ['immich'])

    def test_no_force_off_on_shutdown_timeout(self):
        with patch.object(host, 'virsh') as virsh:
            with self.assertRaises(RuntimeError):
                # Call the real function, which the decision tests mock.
                original_shutdown(self.config, timeout=0)
        virsh.assert_called_once_with('shutdown', 'immich')


original_shutdown = host.shutdown


class Reports(unittest.TestCase):
    def test_socket_inspection_error_is_not_idle_even_with_zero_exit_code(self):
        result = subprocess.CompletedProcess(['ss'], 0, stdout='', stderr='Cannot open netlink socket')
        with patch.object(guest.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError):
                guest.run('ss')

    def test_agent_requires_fresh_explicit_idle_report_and_closes_handle(self):
        valid = {'version': 1, 'idle': True, 'checked_at': time.time()}
        for report, expected in [(valid, True), ({**valid, 'idle': False}, False),
                                 ({**valid, 'idle': 1}, False),
                                 ({**valid, 'checked_at': time.time()-120}, False),
                                 ({**valid, 'checked_at': time.time()+60}, False),
                                 ({'idle':True}, False)]:
            encoded = base64.b64encode(json.dumps(report).encode()).decode()
            with patch.object(host, 'qga', side_effect=[1, {'eof': True, 'buf-b64': encoded}, {}]) as qga:
                self.assertEqual(host.guest_idle({'name':'immich'}), expected)
                self.assertEqual(qga.call_args.args[1]['execute'], 'guest-file-close')

    def test_immich_active_pending_delayed_and_paused_jobs_block_sleep(self):
        names = guest.IMMICH_QUEUES
        queues = [{'name': name, 'statistics': dict.fromkeys(['active', 'waiting', 'delayed', 'paused'], 0)}
                  for name in names]
        self.assertTrue(guest.immich_idle(queues))
        for key in queues[0]['statistics']:
            queues[0]['statistics'][key] = 1
            self.assertFalse(guest.immich_idle(queues))
            queues[0]['statistics'][key] = 0
        with self.assertRaises(ValueError): guest.immich_idle([])
        del queues[0]['statistics']['active']
        with self.assertRaises(KeyError): guest.immich_idle(queues)

    def test_jellyfin_playback_transcoding_and_tasks_block_sleep(self):
        self.assertTrue(guest.jellyfin_idle([], [{'State':'Idle'}]))
        for session in [{'Id':'1', 'NowPlayingItem':{'Id':'movie'}, 'PlayState':{'IsPaused':True}},
                        {'Id':'2', 'TranscodingInfo':{'Bitrate':1}}]:
            self.assertFalse(guest.jellyfin_idle([session], [{'State':'Idle'}]))
        self.assertFalse(guest.jellyfin_idle([], [{'State':'Running'}]))
        with self.assertRaises(ValueError): guest.jellyfin_idle([], [])
        with self.assertRaises(ValueError): guest.jellyfin_idle([], [{'State':'unknown'}])

    def test_backup_marker_overrides_application_checks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(guest, 'BACKUP', Path(directory)):
            (Path(directory)/'immich').mkdir()
            (Path(directory)/'immich/server-was-active').touch()
            self.assertFalse(guest.guest_idle('immich'))

    def test_direct_immich_upload_in_container_namespace_blocks_sleep(self):
        with patch.object(guest, 'run', side_effect=['inactive', '', '123', 'ESTAB']), \
             patch.object(guest, 'api') as api:
            self.assertFalse(guest.guest_idle('immich'))
            api.assert_not_called()


class Network(unittest.TestCase):
    @unittest.skipUnless(shutil.which('systemd-socket-activate')
                         and Path('/usr/lib/systemd/systemd-socket-proxyd').exists(),
                         'systemd socket tools are needed for the live TCP fixture')
    def test_real_socket_activation_forwards_tcp_and_exits_when_idle(self):
        backend = socket.socket()
        backend.bind(('127.0.0.1', 0))
        backend.listen()
        self.addCleanup(backend.close)
        with socket.socket() as allocation:
            allocation.bind(('127.0.0.1', 0))
            frontend = allocation.getsockname()
        proxy = subprocess.Popen(['systemd-socket-activate', '--listen', f'{frontend[0]}:{frontend[1]}',
                                  '/usr/lib/systemd/systemd-socket-proxyd', '--exit-idle-time=1s',
                                  f'127.0.0.1:{backend.getsockname()[1]}'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    client = socket.create_connection(frontend, timeout=3)
                    break
                except ConnectionRefusedError:
                    time.sleep(0.02)
            else:
                self.fail('socket listener did not start')
            backend.settimeout(3)
            with client:
                client.sendall(b'queued request')
                connection, _ = backend.accept()
                with connection:
                    connection.settimeout(3)
                    self.assertEqual(connection.recv(1024), b'queued request')
                    connection.sendall(b'backend response')
                    self.assertEqual(client.recv(1024), b'backend response')
            self.assertEqual(proxy.wait(timeout=5), 0)
        finally:
            if proxy.poll() is None: proxy.terminate()
            proxy.communicate(timeout=5)

    @unittest.skipUnless(shutil.which('qemu-ga'), 'qemu-ga is needed for the live agent fixture')
    def test_real_guest_agent_reads_fresh_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root/'idle.json'
            report.write_text(json.dumps({'version':1, 'idle':True, 'checked_at':time.time()}))
            agent = subprocess.Popen(['qemu-ga', '-m', 'unix-listen', '-p', str(root/'agent.sock'),
                                      '-f', str(root/'agent.pid'), '-t', directory],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (root/'agent.sock').exists(): break
                    if agent.poll() is not None:
                        self.fail(agent.stderr.read().decode())
                    time.sleep(0.02)
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(3)
                    connection.connect(str(root/'agent.sock'))
                    with connection.makefile('rwb') as channel:
                        def qga(config, request):
                            if request['execute'] == 'guest-file-open':
                                request['arguments']['path'] = str(report)
                            channel.write(json.dumps(request).encode()+b'\n')
                            channel.flush()
                            return json.loads(channel.readline())['return']
                        with patch.object(host, 'qga', side_effect=qga):
                            self.assertTrue(host.guest_idle({'name':'immich'}))
                            report.write_text(json.dumps({'version':1, 'idle':True, 'checked_at':time.time()-120}))
                            self.assertFalse(host.guest_idle({'name':'immich'}))
            finally:
                agent.terminate()
                agent.communicate(timeout=5)

    def test_udp_preserves_client_sessions_and_exits_after_idle(self):
        backend = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        backend.bind(('127.0.0.1', 0))
        backend.settimeout(3)
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.bind(('127.0.0.1', 0))
        address = listener.getsockname()
        relay = threading.Thread(target=udp.relay, args=(listener, backend.getsockname()),
                                 kwargs={'peer_timeout':0.15, 'exit_idle':0.1}, daemon=True)
        relay.start()
        clients = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
        self.addCleanup(backend.close)
        origins = []
        for i, client in enumerate(clients):
            self.addCleanup(client.close)
            client.settimeout(3)
            payload = f'client-{i}'.encode()
            client.sendto(payload, address)
            packet, origin = backend.recvfrom(1024)
            self.assertEqual(packet, payload)
            origins.append(origin)
            backend.sendto(packet+b'-reply', origin)
            self.assertEqual(client.recv(1024), payload+b'-reply')
        self.assertNotEqual(*origins)
        relay.join(3)
        self.assertFalse(relay.is_alive())

    def test_tcp_readiness_waits_for_late_backend(self):
        backend = socket.socket()
        backend.bind(('127.0.0.1', 0))
        self.addCleanup(backend.close)
        endpoint = {'protocol':'tcp', 'name':'http', 'guest_port':backend.getsockname()[1]}
        timer = threading.Timer(0.1, backend.listen)
        timer.start()
        self.addCleanup(timer.join)
        host.ready({'name':'immich', 'hostname':'127.0.0.1'}, endpoint, timeout=5)
        connection, _ = backend.accept()
        connection.close()


if __name__ == '__main__':
    unittest.main()
