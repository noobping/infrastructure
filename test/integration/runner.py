#!/usr/bin/env python3
"""Boot the shipped installer, then test the installed image in disposable QEMU VMs."""

import argparse
import base64
import contextlib
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROFILES = ("nas", "workstation")


def resource(data):
    if isinstance(data, str):
        data = data.encode()
    return {"source": "data:;base64," + base64.b64encode(data).decode()}


def decode_resource(value):
    source = value["source"]
    if not source.startswith("data:"):
        raise ValueError("Expected embedded Ignition data, not a remote configuration")
    header, data = source.split(",", 1)
    result = base64.b64decode(data, validate=True) if header.endswith(";base64") else urllib.parse.unquote_to_bytes(data)
    if value.get("compression") == "gzip":
        result = gzip.decompress(result)
    elif value.get("compression") not in (None, ""):
        raise ValueError("Unsupported Ignition compression")
    return result


def file_entry(path, contents, mode=0o644):
    return {"path": path, "mode": mode, "contents": resource(contents)}


def instrument(live, profile, public_key):
    """Keep production Ignition as a merge source; add only documented lab inputs."""
    result = copy.deepcopy(live)
    entries = result.get("storage", {}).get("files", [])
    destinations = [entry for entry in entries if entry["path"] == "/etc/coreos/dest.ign"]
    if len(destinations) != 1:
        raise ValueError("ISO must contain exactly one /etc/coreos/dest.ign (build it with just offline)")
    original = json.loads(decode_resource(destinations[0]["contents"]))
    overlay = {
        "ignition": {"version": original["ignition"]["version"],
                     "config": {"merge": [resource(json.dumps(original))]}},
        "passwd": {"users": [{"name": "root", "sshAuthorizedKeys": [public_key.strip()]}]},
        "storage": {"files": [
            file_entry("/var/lib/infrastructure-test/guest.py", (HERE / "guest.py").read_bytes(), 0o700),
            file_entry("/var/lib/infrastructure-test/profile", profile + "\n"),
            file_entry("/var/lib/infrastructure-test/agent.py", (HERE / "agent.py").read_bytes(), 0o700),
            file_entry("/etc/systemd/journald.conf.d/90-integration.conf",
                       "[Journal]\nForwardToConsole=yes\nTTYPath=/dev/ttyS0\n"),
        ]},
        "systemd": {"units": [{
            "name": "infrastructure-test-agent.service", "enabled": True,
            "contents": "[Unit]\nDescription=Private disposable VM test control\nAfter=local-fs.target\nStartLimitIntervalSec=0\n"
                        "ConditionPathExists=/usr/bin/python3\n[Service]\nType=simple\n"
                        "ExecStart=/usr/bin/python3 /var/lib/infrastructure-test/agent.py\n"
                        "Restart=always\nRestartSec=1\n"
                        "[Install]\nWantedBy=multi-user.target\n",
        }]},
    }
    if profile == "nas":
        overlay["storage"]["files"] += [
            file_entry("/etc/ups/nut.env", "NUT_MODE=standalone\nNUT_UPS_NAME=lab\nNUT_DRIVER=dummy-ups\n"
                       "NUT_DEVICE_PORT=/etc/ups/integration.dev\nNUT_MONITOR_USER=lab\n"
                       "NUT_MONITOR_PASSWORD=integration-only\nNUT_ROLE=primary\nNUT_SHUTDOWNCMD=/usr/bin/true\n", 0o600),
            file_entry("/etc/ups/integration.dev", "ups.mfr: Integration\nups.model: Synthetic UPS\n"
                       "ups.status: OL\nbattery.charge: 100\n"),
        ]
        overlay["storage"]["files"].append({
            "path": "/etc/hosts", "append": [resource(
                "\n127.0.0.1 k3s.vm minecraft.vm jellyfin.vm immich.vm\n")],
        })
        overlay["systemd"]["units"].append({"name": "nightly-shutdown.service", "mask": True})
    destinations[0]["contents"] = resource(json.dumps(overlay))
    entries.append(file_entry("/usr/local/bin/integration-disks", (HERE / "prepare-disks").read_bytes(), 0o700))
    entries.append(file_entry("/etc/systemd/journald.conf.d/90-integration.conf",
                              "[Journal]\nForwardToConsole=yes\nTTYPath=/dev/ttyS0\n"))
    result.setdefault("systemd", {}).setdefault("units", []).append({
        "name": "integration-disks.service", "enabled": True,
        "contents": "\n".join([
            "[Unit]", "Description=Prepare disposable integration fixtures",
            "Requires=pre-install-detect-device.service", "After=pre-install-detect-device.service",
            "Before=coreos-installer.service", "[Service]", "Type=oneshot",
            f"ExecStart=/usr/local/bin/integration-disks {profile}",
            "RemainAfterExit=true", "StandardOutput=journal+console", "StandardError=journal+console",
            "[Install]", "RequiredBy=coreos-installer.service", "",
        ]),
    })
    return result, original, overlay


def run(command, *, timeout=300, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, timeout=timeout, **kwargs)


def capture(command, **kwargs):
    return run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout.decode()


def firmware():
    code, variables = os.environ.get("VM_UEFI_CODE"), os.environ.get("VM_UEFI_VARS")
    if code or variables:
        if not code or not variables or not Path(code).is_file() or not Path(variables).is_file():
            raise ValueError("Set VM_UEFI_CODE and VM_UEFI_VARS to matching raw firmware files")
        return Path(code), Path(variables)
    for directory in ("/usr/share/edk2/ovmf", "/usr/share/OVMF"):
        for suffix in ("", "_4M"):
            pair = tuple(Path(directory) / f"OVMF_{part}{suffix}.fd" for part in ("CODE", "VARS"))
            if all(path.is_file() for path in pair):
                return pair
    raise ValueError("Install edk2-ovmf (Fedora) or ovmf (Debian/Ubuntu)")


def preflight(profiles, accel):
    for binary in ("qemu-system-x86_64", "qemu-img", "swtpm", "ssh", "ssh-keygen", "podman"):
        if not shutil.which(binary):
            raise ValueError(f"Missing {binary}")
    firmware()
    kvm = os.access("/dev/kvm", os.R_OK | os.W_OK)
    if accel == "kvm" and not kvm:
        raise ValueError("/dev/kvm is unavailable; enable KVM or explicitly use VM_TEST_ACCEL=tcg (much slower)")
    for profile in profiles:
        iso = ROOT / f"dist/iso/{profile}-offline-x86_64.iso"
        if not iso.is_file() or not Path(str(iso) + ".sha256").is_file():
            raise ValueError(f"Build the installer first: just offline {profile} amd64")
        print(f"{profile}: installer found ({iso.stat().st_size // 2**20} MiB)", flush=True)
    print(f"Acceleration: {accel}; KVM {'available' if kvm else 'unavailable'}", flush=True)
    return accel


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def installer(state, *arguments):
    # Do not relabel the checkout or expose its other files to this container.
    return capture([
        "podman", "run", "--rm", "--network", "none", "--security-opt", "label=disable",
        "-v", f"{state}:/test:rw", "quay.io/coreos/coreos-installer:release", *arguments,
    ])


def qemu_options(state, runtime, accel, port, memory, cpus):
    def escaped(path):
        return str(path).replace(",", ",,")
    args = [
        "qemu-system-x86_64", "-name", f"integration-{state.name}", "-machine", "q35",
        "-accel", accel, "-cpu", "host" if accel == "kvm" else "max", "-m", str(memory), "-smp", str(cpus),
        "-drive", f"if=pflash,format=raw,readonly=on,file={escaped(state / 'uefi-code.fd')}",
        "-drive", f"if=pflash,format=raw,file={escaped(state / 'uefi-vars.fd')}",
        "-drive", f"if=none,id=os,format=qcow2,file={escaped(state / 'os.qcow2')}",
        "-device", "ide-hd,drive=os,bus=ide.0,serial=integration-os,bootindex=1",
        "-drive", f"if=none,id=installer,media=cdrom,format=raw,readonly=on,file={escaped(state / 'installer.iso')}",
        "-device", "ide-cd,drive=installer,bus=ide.1,bootindex=2",
        "-boot", "strict=on", "-display", "none", "-vga", "virtio",
        "-device", "qemu-xhci", "-device", "usb-tablet",
        "-chardev", f"socket,id=chrtpm,path={runtime}/tpm.sock",
        "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", "tpm-tis,tpmdev=tpm0",
        "-serial", f"file:{state}/serial.log", "-monitor", "none",
        "-qmp", f"unix:{runtime}/qmp.sock,server=on,wait=off",
        "-device", "virtio-serial-pci",
        "-chardev", f"socket,id=control,path={runtime}/control.sock,server=on,wait=off",
        "-device", "virtserialport,chardev=control,name=infrastructure.test",
        # No LAN bridge, outbound network, or connection to the real NAS.
        "-netdev", f"user,id=lab,restrict=on,hostfwd=tcp:127.0.0.1:{port}-:22",
        "-device", "virtio-net-pci,netdev=lab",
    ]
    for index, name in enumerate(("ssd", "hdd"), start=2):
        args += ["-drive", f"if=none,id={name},format=qcow2,file={escaped(state / (name + '.qcow2'))}",
                 "-device", f"ide-hd,drive={name},bus=ide.{index},serial=integration-{name}"]
    args += ["-drive", f"if=none,id=decoy,format=qcow2,file={escaped(state / 'usb.qcow2')}",
             "-device", "usb-storage,drive=decoy,serial=integration-usb"]
    return args


def ssh_command(state, port, command):
    return ["ssh", "-F", "/dev/null", "-i", str(state / "key"), "-p", str(port),
            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=3",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "root@127.0.0.1", command]


def guest(state, command, *, timeout=300, stdin=None):
    settings = json.loads((state / "connection.json").read_text())
    size = os.fstat(stdin.fileno()).st_size if stdin else 0
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(timeout)
        connection.connect(settings["control_socket"])
        request = {"command": command, "stdin_size": size, "timeout": max(1, timeout - 2)}
        connection.sendall(json.dumps(request).encode() + b"\n")
        if stdin:
            while chunk := stdin.read(1024 * 1024):
                connection.sendall(chunk)
        with connection.makefile("rb") as stream:
            response = json.loads(stream.readline())
    if response["code"]:
        raise subprocess.CalledProcessError(response["code"], ["guest", command],
                                            response["stdout"].encode(), response["stderr"].encode())
    # Allow the one-shot channel reader to exit and restart before reconnecting.
    time.sleep(1.2)
    return response["stdout"]


@contextlib.contextmanager
def process(command, log, **kwargs):
    with log.open("wb") as output:
        child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, **kwargs)
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)


def add_result(report, name, status, detail=""):
    report["tests"].append({"name": name, "status": status, "detail": str(detail)})
    print(f"  {status.upper()}: {name}" + (f": {detail}" if status != "pass" else ""), flush=True)


def parse_results(output):
    results = json.loads(output)
    if not isinstance(results, list) or not results:
        raise ValueError("Guest returned no assertions")
    names = set()
    for result in results:
        name = result.get("name") if isinstance(result, dict) else None
        if not isinstance(name, str) or not name or name in names or result.get("status") not in ("pass", "fail", "skip"):
            raise ValueError("Guest returned invalid or duplicate assertions")
        names.add(name)
    if "Ignition settings, encrypted root and persistent data" not in names or "no unexpected failed services" not in names:
        raise ValueError("Guest report is incomplete")
    return results


def write_report(state, report):
    (state / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    tests = report["tests"]
    suite = ET.Element("testsuite", name=report["profile"], tests=str(len(tests)),
                       failures=str(sum(t["status"] == "fail" for t in tests)),
                       skipped=str(sum(t["status"] == "skip" for t in tests)))
    for test in tests:
        case = ET.SubElement(suite, "testcase", name=test["name"], classname=report["profile"])
        if test["status"] != "pass":
            ET.SubElement(case, "failure" if test["status"] == "fail" else "skipped").text = test["detail"]
    ET.ElementTree(suite).write(state / "junit.xml", encoding="utf-8", xml_declaration=True)


def screenshot(state, runtime):
    # QMP is connected only to this run's private Unix socket.
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(runtime / "qmp.sock"))
        with connection.makefile("rwb") as stream:
            json.loads(stream.readline())
            for request in ({"execute": "qmp_capabilities"},
                            {"execute": "screendump", "arguments": {"filename": str(state / "screen.png"), "format": "png"}}):
                stream.write(json.dumps(request).encode() + b"\n")
                stream.flush()
                while True:
                    response = json.loads(stream.readline())
                    if "return" in response or "error" in response:
                        break
                if "error" in response:
                    raise RuntimeError(response["error"])


def remaining(deadline, maximum=300):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Integration deadline expired; inspect serial.log, guest-journal.log and qemu.log")
    return min(maximum, seconds)


def wait_image(state, port, profile, qemu, deadline, previous_boot=None):
    notice = 0
    while True:
        remaining(deadline)
        if qemu.poll() is not None:
            raise RuntimeError(f"QEMU exited before tests completed ({qemu.returncode}); see qemu.log and serial.log")
        serial = state / "serial.log"
        if serial.exists():
            with serial.open("rb") as source:
                source.seek(max(0, serial.stat().st_size - 256 * 1024))
                tail = source.read().decode(errors="replace")
            if "No space left on device" in tail:
                raise RuntimeError("Guest ran out of space during installation/rebase; inspect serial.log and retained disks")
        try:
            output = guest(state, "cat /proc/sys/kernel/random/boot_id; rpm-ostree status --json", timeout=10)
            boot_id, raw = output.split("\n", 1)
            status = json.loads(raw)
            booted = next(item for item in status["deployments"] if item.get("booted"))
            reference = booted.get("container-image-reference", "")
            (state / "last-deployment.json").write_text(json.dumps(status, indent=2) + "\n")
            if profile in reference and (previous_boot is None or boot_id != previous_boot):
                return boot_id, reference
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, StopIteration):
            pass
        if time.monotonic() >= notice:
            print(f"  Waiting for installed {profile} image{' to reboot' if previous_boot else ''}...", flush=True)
            notice = time.monotonic() + 30
        time.sleep(min(5, remaining(deadline)))


def seed_containers(state, port, deadline, report, pull):
    # Discover references from the image under test, not from the current checkout.
    command = "sed -n 's/^Image=//p' /etc/containers/systemd/*.container /usr/share/containers/systemd/*.container"
    references = sorted(set(guest(state, command, timeout=remaining(deadline)).splitlines()))
    report["container_images"] = []
    for index, reference in enumerate(references):
        if not reference or any(char.isspace() for char in reference) or reference.startswith("-"):
            raise ValueError(f"Invalid image reference in installed Quadlet: {reference!r}")
        if pull:
            run(["podman", "pull", reference], timeout=remaining(deadline, 600), stdout=subprocess.DEVNULL)
        details = json.loads(capture(["podman", "image", "inspect", reference], timeout=remaining(deadline)))[0]
        report["container_images"].append({"reference": reference, "id": details["Id"], "digests": details.get("RepoDigests", [])})
        archive = state / f"container-{index}.tar"
        run(["podman", "save", "-o", archive, reference], timeout=remaining(deadline, 600), stdout=subprocess.DEVNULL)
        with archive.open("rb") as source:
            guest(state, "podman load", stdin=source, timeout=remaining(deadline, 1200))
        archive.unlink()
    # Earlier offline pull failures must be retried now that their images exist.
    guest(state, "systemctl reset-failed cockpit.service registry.service jellyfin.service; systemctl start --no-block cockpit.service registry.service jellyfin.service",
          timeout=remaining(deadline))


def collect(state, port):
    for name, command in {
        "guest-journal.log": "journalctl --no-pager -n 5000",
        "guest-units.log": "systemctl --failed --no-pager; systemctl list-units --all --no-pager; podman ps -a",
        "guest-storage.log": "lsblk -f; findmnt; cat /etc/fstab",
        "guest-progress.json": "cat /var/lib/infrastructure-test/progress.json",
    }.items():
        with contextlib.suppress(Exception):
            (state / name).write_text(guest(state, command, timeout=30))


def test_profile(profile, args):
    state = ROOT / "dist/integration" / (time.strftime("%Y%m%d-%H%M%S-") + profile + "-" + uuid.uuid4().hex[:8])
    state.mkdir(parents=True, mode=0o700)
    print(f"Testing {profile}; results: {state}", flush=True)
    report = {"profile": profile, "acceleration": args.accel, "tests": [],
              "overlay": ["ephemeral root SSH key", "synthetic SATA/USB disks", "pre-install disk assertions",
                          "private serial test-control service", "guest assertions in /var/lib/infrastructure-test",
                          "serial journal forwarding", "isolated user-mode network"],
              "revision": capture(["git", "-C", ROOT, "rev-parse", "HEAD"]).strip(),
              "dirty": bool(capture(["git", "-C", ROOT, "status", "--porcelain"]).strip())}
    if profile == "nas":
        report["overlay"] += ["nightly shutdown masked", "export client names resolve to loopback",
                              "NUT dummy UPS and harmless shutdown command"]
    deadline = time.monotonic() + args.timeout
    try:
        source = ROOT / f"dist/iso/{profile}-offline-x86_64.iso"
        digest = sha256(source)
        expected = Path(str(source) + ".sha256").read_text().split()[0]
        if digest != expected:
            raise ValueError(f"Installer checksum mismatch: {source}")
        report["installer"] = {"path": str(source), "sha256": digest}
        add_result(report, "installer checksum", "pass")
        run(["cp", "--reflink=auto", source, state / "installer.iso"])
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", state / "key"])
        live = json.loads(installer(state, "iso", "ignition", "show", "/test/installer.iso"))
        patched, original, overlay = instrument(live, profile, (state / "key.pub").read_text())
        probe = next(entry for entry in overlay["storage"]["files"] if entry["path"].endswith("/guest.py"))
        report["guest_assertions_sha256"] = hashlib.sha256(decode_resource(probe["contents"])).hexdigest()
        (state / "production-destination.json").write_text(json.dumps(original, indent=2) + "\n")
        (state / "test-destination.json").write_text(json.dumps(overlay, indent=2) + "\n")
        (state / "live.json").write_text(json.dumps(patched) + "\n")
        installer(state, "iso", "ignition", "embed", "--force", "--ignition-file", "/test/live.json", "/test/installer.iso")
        for name, size in (("os", "64G"), ("ssd", "96G"), ("hdd", "128G"), ("usb", "1G")):
            run(["qemu-img", "create", "-q", "-f", "qcow2", state / f"{name}.qcow2", size])
        for source_fw, name in zip(firmware(), ("uefi-code.fd", "uefi-vars.fd")):
            shutil.copyfile(source_fw, state / name)
        (state / "tpm").mkdir()
        with tempfile.TemporaryDirectory(prefix="infra-test-") as temporary:
            runtime = Path(temporary)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            (state / "connection.json").write_text(json.dumps({"address": "127.0.0.1", "ssh_port": port,
                                                                "control_socket": str(runtime / "control.sock")}) + "\n")
            with process(["swtpm", "socket", "--tpm2", "--tpmstate", "dir=tpm", "--ctrl", f"type=unixio,path={runtime}/tpm.sock"],
                         state / "tpm.log", cwd=state) as tpm:
                for _ in range(100):
                    if (runtime / "tpm.sock").exists():
                        break
                    if tpm.poll() is not None:
                        raise RuntimeError("swtpm failed; inspect tpm.log")
                    time.sleep(0.05)
                else:
                    raise RuntimeError("swtpm socket did not appear")
                command = qemu_options(state, runtime, args.accel, port, args.memory, args.cpus)
                (state / "qemu-command.json").write_text(json.dumps(command, indent=2) + "\n")
                with process(command, state / "qemu.log") as qemu:
                    try:
                        boot_id, reference = wait_image(state, port, profile, qemu, deadline)
                        report["booted_image"] = reference
                        add_result(report, "automatic install and image rebase", "pass")
                        if profile == "nas":
                            seed_containers(state, port, deadline, report, args.pull)
                        for phase in ("initial", "reboot"):
                            if phase == "reboot":
                                with contextlib.suppress(subprocess.SubprocessError, OSError, ValueError):
                                    guest(state, "systemctl --no-block reboot", timeout=10)
                                boot_id, _ = wait_image(state, port, profile, qemu, deadline, previous_boot=boot_id)
                                add_result(report, "unattended reboot with preserved TPM and encrypted root", "pass")
                            output = guest(state, f"python3 /var/lib/infrastructure-test/guest.py {profile} {phase}",
                                           timeout=remaining(deadline, 1800))
                            (state / f"guest-{phase}.json").write_text(output)
                            for result in parse_results(output):
                                add_result(report, phase + ": " + result["name"], result["status"], result.get("detail", ""))
                            # The guest checks include startup grace for policy and
                            # IPS; do not treat a warming firewall as an SSH failure.
                            try:
                                capture(ssh_command(state, port, "true"), timeout=10)
                                add_result(report, phase + ": SSH reachable through guest firewall", "pass")
                            except subprocess.SubprocessError:
                                add_result(report, phase + ": SSH reachable through guest firewall", "fail", "SSH unavailable after service startup; diagnostics use the private serial control channel")
                            write_report(state, report)
                    finally:
                        with contextlib.suppress(Exception):
                            screenshot(state, runtime)
                        collect(state, port)
        if not any(test["status"] == "fail" for test in report["tests"]) and not args.keep:
            for path in state.glob("*.qcow2"):
                path.unlink()
            (state / "installer.iso").unlink()
            (state / "key").unlink()
    except KeyboardInterrupt:
        add_result(report, "test execution", "fail", "Interrupted")
        raise
    except Exception as error:
        detail = str(error)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            detail += "\n" + error.stderr.decode(errors="replace")[-6000:]
        add_result(report, "test execution", "fail", detail)
    finally:
        write_report(state, report)
    failures = sum(test["status"] == "fail" for test in report["tests"])
    print(f"{profile}: {'FAIL' if failures else 'PASS'}; report: {state / 'report.json'}", flush=True)
    return not failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=(*PROFILES, "all"), default="all", nargs="?")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--accel", choices=("kvm", "tcg"), default=os.environ.get("VM_TEST_ACCEL", "kvm"))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("VM_TEST_TIMEOUT", "3600")))
    parser.add_argument("--memory", type=int, default=int(os.environ.get("VM_TEST_MEMORY", "12288")))
    parser.add_argument("--cpus", type=int, default=int(os.environ.get("VM_TEST_CPUS", "4")))
    parser.add_argument("--keep", action="store_true", help="keep disks even after successful tests (failures are always kept)")
    parser.add_argument("--pull", action="store_true", help="fetch NAS application images; otherwise require them in the host Podman cache")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.memory < 4096 or args.cpus < 1:
        parser.error("timeout/CPUs must be positive and memory must be at least 4096 MiB")
    profiles = PROFILES if args.profile == "all" else (args.profile,)
    os.umask(0o077)
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        preflight(profiles, args.accel)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    if args.preflight:
        return 0
    try:
        results = [test_profile(profile, args) for profile in profiles]
    except KeyboardInterrupt:
        return 130
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
