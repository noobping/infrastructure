#!/usr/bin/env python3
"""Fast harness checks; these do not claim to validate an installed VM."""

import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("integration_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
agent_spec = importlib.util.spec_from_file_location("integration_agent", Path(__file__).with_name("agent.py"))
agent = importlib.util.module_from_spec(agent_spec)
agent_spec.loader.exec_module(agent)


class HarnessTests(unittest.TestCase):
    def live(self):
        original = {
            "ignition": {"version": "3.5.0"},
            "passwd": {"users": [{"name": "nick", "uid": 1000}]},
            "storage": {"files": [runner.file_entry("/etc/containers/policy.json", "signed policy")]},
            "systemd": {"units": [{"name": "rebase-to-nas.service", "enabled": True, "contents": "production rebase"}]},
        }
        return {"ignition": {"version": "3.3.0", "config": {"merge": [runner.resource("live original")]}},
                "storage": {"files": [runner.file_entry("/etc/coreos/dest.ign", json.dumps(original)),
                                      runner.file_entry("/etc/coreos/installer.d/0000-customize.yaml", "production installer")]},
                "systemd": {"units": [{"name": "pre-install-detect-device.service", "enabled": True}]}}, original

    def test_preserves_production_settings_trust_and_disk_selector(self):
        live, original = self.live()
        before = json.dumps(live)
        result, saved, overlay = runner.instrument(live, "nas", "ssh-ed25519 test-key")
        self.assertEqual(json.dumps(live), before)
        self.assertEqual(saved, original)
        self.assertEqual(json.loads(runner.decode_resource(overlay["ignition"]["config"]["merge"][0])), original)
        self.assertEqual(result["ignition"], live["ignition"])
        self.assertEqual(result["storage"]["files"][1], live["storage"]["files"][1])
        self.assertEqual(result["systemd"]["units"][0], live["systemd"]["units"][0])
        self.assertEqual(overlay["passwd"]["users"], [{"name": "root", "sshAuthorizedKeys": ["ssh-ed25519 test-key"]}])

    def test_requires_real_installer_destination(self):
        with self.assertRaisesRegex(ValueError, "dest.ign"):
            runner.instrument({"storage": {"files": []}}, "nas", "key")
        live, _ = self.live()
        live["storage"]["files"].append(live["storage"]["files"][0])
        with self.assertRaises(ValueError):
            runner.instrument(live, "nas", "key")

    def test_decodes_gzip_ignition_and_rejects_remote_input(self):
        compressed = {"source": "data:;base64," + base64.b64encode(gzip.compress(b'{"test": 1}')).decode(), "compression": "gzip"}
        self.assertEqual(json.loads(runner.decode_resource(compressed)), {"test": 1})
        self.assertEqual(runner.decode_resource({"source": "data:,a%20b"}), b"a b")
        with self.assertRaises(ValueError):
            runner.decode_resource({"source": "https://example.invalid/config"})

    def test_no_nas_overrides_on_workstation(self):
        live, _ = self.live()
        _, _, overlay = runner.instrument(live, "workstation", "key")
        self.assertEqual([unit["name"] for unit in overlay["systemd"]["units"]], ["infrastructure-test-agent.service"])
        self.assertFalse(any(entry["path"].startswith("/etc/ups") for entry in overlay["storage"]["files"]))

    def test_qemu_is_isolated_and_only_uses_run_disks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "a,b"
            options = runner.qemu_options(state, Path("/tmp/private"), "kvm", 4321, 12288, 4)
            self.assertIn("user,id=lab,restrict=on,hostfwd=tcp:127.0.0.1:4321-:22", options)
            self.assertNotIn("-enable-kvm", options)
            self.assertNotIn("bridge", " ".join(options))
            drives = [options[i + 1] for i, token in enumerate(options) if token == "-drive"]
            self.assertTrue(all(str(state).replace(",", ",,") in drive for drive in drives))
            self.assertFalse(any("/dev/" in drive for drive in drives))
            self.assertIn("ide-hd,drive=os,bus=ide.0,serial=integration-os,bootindex=1", options)
            self.assertIn("ide-cd,drive=installer,bus=ide.1,bootindex=2", options)
            self.assertIn("usb-storage,drive=decoy,serial=integration-usb", options)

    def test_ssh_does_not_use_user_configuration(self):
        options = runner.ssh_command(Path("/tmp/test"), 2222, "true")
        self.assertEqual(options[1:3], ["-F", "/dev/null"])
        self.assertIn("IdentitiesOnly=yes", options)
        self.assertIn("UserKnownHostsFile=/dev/null", options)
        self.assertIn("root@127.0.0.1", options)

    def test_process_is_reaped_after_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                with runner.process([sys.executable, "-c", "import time; time.sleep(60)"], Path(directory) / "log") as child:
                    raise RuntimeError("fixture")
            self.assertIsNotNone(child.poll())

    def test_deadline_and_early_qemu_exit_fail(self):
        with self.assertRaises(TimeoutError):
            runner.remaining(time.monotonic() - 1)
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.Popen([sys.executable, "-c", "pass"])
            child.wait()
            with self.assertRaisesRegex(RuntimeError, "QEMU exited"):
                runner.wait_image(Path(directory), 2222, "nas", child, time.monotonic() + 30)

    def test_kvm_required_unless_explicit_tcg(self):
        with patch.object(runner.shutil, "which", return_value="/usr/bin/tool"), patch.object(runner, "firmware"), \
                patch.object(runner.os, "access", return_value=False):
            with self.assertRaisesRegex(ValueError, "KVM"):
                runner.preflight([], "kvm")
            self.assertEqual(runner.preflight([], "tcg"), "tcg")

    def test_machine_readable_failures_and_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            report = {"profile": "nas", "tests": [
                {"name": "install", "status": "pass"},
                {"name": "NFS", "status": "fail", "detail": "Permission denied <root>"},
                {"name": "UPS hardware", "status": "skip", "detail": "No physical UPS"},
            ]}
            runner.write_report(state, report)
            self.assertEqual(json.loads((state / "report.json").read_text()), report)
            suite = ET.parse(state / "junit.xml").getroot()
            self.assertEqual(suite.attrib["failures"], "1")
            self.assertEqual(suite.attrib["skipped"], "1")
            self.assertEqual(suite.find("testcase/failure").text, "Permission denied <root>")

    def exchange(self, directory, function):
        state = Path(directory)
        control = str(state / "control.sock")
        (state / "connection.json").write_text(json.dumps({"control_socket": control}))
        errors = []
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(control)
            server.listen(1)
            server.settimeout(10)
            def respond():
                try:
                    with server.accept()[0] as connection, connection.makefile("rwb", buffering=0) as stream:
                        agent.serve(stream, directory)
                except Exception as error:
                    errors.append(error)
            worker = threading.Thread(target=respond, daemon=True)
            worker.start()
            try:
                return function(state)
            finally:
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])

    def test_private_channel_streams_binary_input(self):
        with tempfile.TemporaryDirectory() as directory:
            data = bytes(range(256)) * 8192
            source = Path(directory) / "binary"
            source.write_bytes(data)
            def request(state):
                with source.open("rb") as input_file:
                    return runner.guest(state, "sha256sum", stdin=input_file, timeout=10)
            output = self.exchange(directory, request)
            self.assertEqual(output.split()[0], hashlib.sha256(data).hexdigest())

    def test_private_channel_preserves_guest_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                self.exchange(directory, lambda state: runner.guest(state, "echo fixture-error >&2; exit 7", timeout=10))
            self.assertEqual(caught.exception.returncode, 7)
            self.assertEqual(caught.exception.stderr, b"fixture-error\n")

    def test_private_channel_enforces_guest_command_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                self.exchange(directory, lambda state: runner.guest(state, "exec sleep 60", timeout=3))
            self.assertEqual(caught.exception.returncode, 124)

    def test_incomplete_guest_reports_cannot_pass(self):
        for report in ([], [{"name": "only one check", "status": "pass"}],
                       [{"name": "case", "status": "unknown"}],
                       [{"name": "duplicate", "status": "pass"}] * 2):
            with self.subTest(report=report), self.assertRaises(ValueError):
                runner.parse_results(json.dumps(report))


if __name__ == "__main__":
    unittest.main()
