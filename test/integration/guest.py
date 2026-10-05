#!/usr/bin/env python3
"""Assertions inside the disposable installed VM. Never run this on a real host."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

STATE = Path("/var/lib/infrastructure-test")
RESULTS = []
STARTUP_DEADLINE = 0


def command(*args, timeout=120, check=True, **kwargs):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, **kwargs)
    if check and result.returncode:
        raise AssertionError(f"{' '.join(args)}: exit {result.returncode}\n{result.stdout[-3000:]}{result.stderr[-3000:]}")
    return result.stdout.strip() if check else result


def require(value, detail):
    if not value:
        raise AssertionError(detail)


def case(name, function):
    started = time.monotonic()
    try:
        function()
        result = {"name": name, "status": "pass"}
    except Exception as error:
        result = {"name": name, "status": "fail", "detail": str(error)}
    result["seconds"] = round(time.monotonic() - started, 2)
    RESULTS.append(result)
    (STATE / "progress.json").write_text(json.dumps(RESULTS, indent=2) + "\n")
    # Progress remains observable while the controller waits for the full report.
    subprocess.run(["logger", "-t", "infrastructure-test", f"{result['status'].upper()}: {name}"], check=False)


def skip(name, reason):
    RESULTS.append({"name": name, "status": "skip", "detail": reason})


def eventually(function, seconds=None):
    # Services start concurrently. Share one startup grace period so multiple
    # failed units cannot each consume a fresh three-minute timeout.
    deadline = STARTUP_DEADLINE if seconds is None else time.monotonic() + seconds
    while True:
        try:
            return function()
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(3)


def active(unit):
    command("systemctl", "is-active", "--quiet", unit, timeout=15)


def oneshot(unit):
    values = dict(line.split("=", 1) for line in command(
        "systemctl", "show", unit, "-p", "LoadState,ActiveState,Result,ExecMainStartTimestampMonotonic").splitlines())
    require(values["LoadState"] == "loaded", f"{unit} is missing")
    require(values["Result"] == "success" and values["ActiveState"] != "activating"
            and int(values["ExecMainStartTimestampMonotonic"]) > 0, f"{unit}: {values}")


def http(url, data=None, method=None):
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/octet-stream")
    # Never use a proxy inherited from the environment for loopback tests.
    try:
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15)
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode(errors="replace")
        raise AssertionError(f"HTTP {error.code} for {urllib.parse.urlparse(url).path}: {detail}") from error


def basic(profile, phase):
    require(command("hostname") == profile, "Hostname was not applied")
    require(command("id", "-u", "nick") == "1000", "nick UID differs from Ignition")
    require(Path("/etc/localtime").resolve() == Path("/usr/share/zoneinfo/Europe/Amsterdam"), "Wrong timezone")
    require(command("getenforce") == "Enforcing", "SELinux is not enforcing")
    require("crypto_LUKS" in command("lsblk", "-no", "FSTYPE"), "Root encryption is missing")
    require(Path("/dev/tpmrm0").exists(), "Virtual TPM is missing")
    require(Path("/var/rebase.done" if profile == "nas" else "/var/lib/rebase.done").is_file(), "Rebase marker missing")
    canary = STATE / "persistent-canary"
    if phase == "initial":
        canary.write_text("survives reboot\n")
    require(canary.read_text() == "survives reboot\n", "Persistent data changed after reboot")
    if profile == "nas":
        arguments = Path("/proc/cmdline").read_text().split()
        require("libata.eh_timeout=240" in arguments and "crashkernel=512M" in arguments, "NAS kernel arguments missing")


def disks(profile):
    rows = json.loads(command("lsblk", "-J", "-d", "-o", "PATH,SERIAL"))["blockdevices"]
    devices = {row["serial"]: row["path"] for row in rows}
    root = command("findmnt", "-n", "-o", "SOURCE", "/sysroot").split("[", 1)[0]
    require("integration-os" in command("lsblk", "-s", "-n", "-o", "SERIAL", root), "Installer chose a non-OS disk")
    names = ("usb",) if profile == "nas" else ("usb", "ssd", "hdd")
    for name in names:
        with open(devices["integration-" + name], "rb") as device:
            require(device.read(64).startswith(f"infrastructure-{name}-preserved\n".encode()), f"Installer overwrote {name} fixture")


def antivirus():
    # EICAR is harmless standard antivirus test data, sent directly to clamd.
    eicar = STATE / "eicar.com"
    eicar.write_text('X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*')
    try:
        result = command("clamdscan", "--fdpass", str(eicar), check=False)
        require(result.returncode == 1 and "FOUND" in result.stdout, result.stdout + result.stderr)
    finally:
        eicar.unlink()


def workstation(phase):
    for unit in ("gdm.service", "firewalld.service", "avahi-daemon.service", "cups.socket", "pcscd.socket",
                 "cachefilesd.service"):
        case(unit, lambda unit=unit: eventually(lambda: active(unit)))
    case("libvirt responds through its system socket", lambda: command("virsh", "-c", "qemu:///system", "list", "--all"))

    def defaults():
        require(command("systemctl", "get-default") == "graphical.target", "Wrong boot target")
        require("nl_NL.UTF-8" in Path("/etc/locale.conf").read_text(), "System locale missing")
        require("XKBVARIANT=intl" in Path("/etc/vconsole.conf").read_text(), "Keyboard variant missing")
        settings = (
            ("org.gnome.desktop.interface", "accent-color", "'green'"),
            ("org.gnome.desktop.background", "picture-uri", "'file:///usr/share/backgrounds/wallpaper.png'"),
            ("org.gnome.system.locale", "region", "'nl_NL.UTF-8'"),
        )
        for schema, key, expected in settings:
            actual = command("runuser", "-u", "nick", "--", "dbus-run-session", "gsettings", "get", schema, key)
            require(actual == expected, f"{schema} {key}: expected {expected}, got {actual}")
        require(Path("/usr/share/backgrounds/wallpaper.png").stat().st_size > 1000, "Wallpaper missing")
        command("authselect", "check")
        command("authselect", "is-feature-enabled", "with-fingerprint")
    case("effective GNOME, locale, keyboard and login settings", defaults)

    def policy():
        eventually(lambda: oneshot("infrastructure-policy.service"))
        home = Path(pwd.getpwnam("nick").pw_dir)
        require(stat.S_IMODE(home.stat().st_mode) == 0o700 and home.stat().st_uid == 1000, "Home permissions incorrect")
        for source in Path("/etc/skel").rglob("*"):
            if source.is_file() and not source.is_symlink():
                target = home / source.relative_to("/etc/skel")
                require(target.exists() and target.stat().st_uid == 1000, f"Skeleton entry missing or wrongly owned: {target}")
        target = home / ".bashrc"
        if phase == "initial":
            with target.open("a") as output:
                output.write("\n# integration user customization\n")
        before = target.read_bytes()
        command("systemctl", "restart", "infrastructure-policy.service", timeout=600)
        require(target.read_bytes() == before and b"integration user customization" in before, "Policy overwrote user content")
    case("home and skeleton policy preserves user changes", policy)

    def flatpaks():
        eventually(lambda: require(Path("/var/lib/system-flatpaks.done").is_file(), "Offline Flatpak installation did not finish"), seconds=600)
        expected = {line.split("#", 1)[0].strip() for line in Path("/etc/recommended/flathub").read_text().splitlines()} - {""}
        installed = set(command("flatpak", "list", "--system", "--app", "--columns=application").splitlines())
        require(expected <= installed, f"Missing Flatpaks: {sorted(expected - installed)}")
    case("all bundled Flatpaks install without network", flatpaks)
    skip("desktop interaction and physical peripherals", "Settings and GDM checked; no login, GPU, printer, fingerprint reader or audio hardware in this lab")
    skip("ChatGPT download and online Flatpak updates", "External network disabled; use existing installer/cache tests for these paths")


def storage():
    mounts = {
        "/var/srv/ssd": "ssd", "/var/lib/containers": "ssd", "/var/srv/docs": "ssd",
        "/var/srv/photos": "ssd", "/var/srv/music": "ssd", "/var/srv/music/touhou": "ssd",
        "/var/srv/books": "ssd", "/var/srv/git": "ssd", "/var/srv/videos": "ssd",
        "/var/srv/hdd": "hdd", "/var/srv/data": "hdd",
    }
    for path, label in mounts.items():
        require(command("findmnt", "-n", "-o", "FSTYPE", "--mountpoint", path) == "btrfs", f"{path} fell back to OS disk")
        require(command("findmnt", "-n", "-o", "LABEL", "--mountpoint", path) == label, f"Wrong disk for {path}")
    require(Path("/var/srv/docs/example.txt").read_text() == "integration document\n", "Seed document changed")
    require(Path("/var/srv/photos/example.png").read_bytes().startswith(b"\x89PNG"), "Seed photo missing")
    for name, uid in (("music", 1001), ("minecraft", 1003), ("docs", 1004), ("photos", 1005), ("videos", 1006)):
        require(pwd.getpwnam(name).pw_uid == uid, f"Wrong UID for {name}")
    uploads = Path("/var/lib/containers/immich/data")
    require(uploads.stat().st_uid == 1005 and uploads.stat().st_gid == 1005, "Wrong upload ownership")


def nfs():
    # Real kernel NFS client/server, in a private mount namespace (see main).
    active("nfs-server.service")
    original = hashlib.sha256(Path("/var/srv/photos/example.png").read_bytes()).hexdigest()
    root = Path("/run/infrastructure-nfs-test")
    root.mkdir(exist_ok=True)
    mounted = []
    try:
        for label, export in (("photos", "/var/srv/photos"), ("uploads", "/var/lib/containers/immich/data"),
                              ("artifacts", "/var/srv/ssd/artifacts")):
            target = root / label
            target.mkdir(exist_ok=True)
            command("mount", "-t", "nfs", "-o", "vers=4,proto=tcp,hard,timeo=10,retrans=2", "127.0.0.1:" + export, str(target))
            mounted.append(target)
        require((root / "photos/example.png").read_bytes() == Path("/var/srv/photos/example.png").read_bytes(), "NFS read differs")
        result = command("touch", str(root / "photos/must-not-write"), check=False)
        require(result.returncode != 0, "Original library accepts writes")
        result = command("touch", str(root / "uploads/root-must-not-write"), check=False)
        require(result.returncode != 0, "Root squashing failed")
        command("setpriv", "--reuid", "1005", "--regid", "1005", "--clear-groups", "touch", str(root / "uploads/phone-upload"))
        require(Path("/var/lib/containers/immich/data/phone-upload").stat().st_uid == 1005, "Upload has wrong UID")
        require((root / "artifacts/example.txt").read_text() == "integration artifact\n", "Artifact export failed")
    finally:
        for target in reversed(mounted):
            command("umount", str(target), check=False, timeout=20)
    require(hashlib.sha256(Path("/var/srv/photos/example.png").read_bytes()).hexdigest() == original, "Original changed")


def backups(phase):
    if phase == "reboot":
        require(Path("/var/srv/hdd/integration-restored/example.png").read_bytes() == Path("/var/srv/photos/example.png").read_bytes(),
                "Restored photo did not survive reboot")
        return
    env = dict(os.environ, BTRFS_BACKUP_SUBVOLUMES="photos docs", BTRFS_BACKUP_RETENTION="2")
    for iteration in range(3):
        Path("/var/srv/photos/iteration.txt").write_text(str(iteration))
        command("/usr/libexec/infrastructure/btrfs-backup", env=env)
        time.sleep(1.1)
    root = Path("/var/srv/hdd/backups/ssd/photos")
    snapshots = sorted(root.iterdir())
    require(len(snapshots) == 2, "Backup retention did not prune to two snapshots")
    require((snapshots[-1] / "iteration.txt").read_text() == "2", "Incremental backup missed changed file")
    require(command("btrfs", "property", "get", str(snapshots[-1]), "ro") == "ro=true", "Backup is writable")
    restored = "/var/srv/hdd/integration-restored"
    command("btrfs", "subvolume", "snapshot", str(snapshots[-1]), restored)
    require(Path(restored + "/example.png").read_bytes() == Path("/var/srv/photos/example.png").read_bytes(), "Restore differs")
    # Inject a destination failure, then verify the next backup can still run.
    bad = STATE / "not-a-directory"
    bad.write_text("injected failure\n")
    result = command("/usr/libexec/infrastructure/btrfs-backup", env=dict(env, BTRFS_BACKUP_DESTINATION_ROOT=str(bad)), check=False)
    require(result.returncode != 0, "Injected backup failure was ignored")
    command("/usr/libexec/infrastructure/btrfs-backup", env=env)


def registry(phase, port=5000):
    body = b"synthetic registry blob\n"
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    base = f"http://127.0.0.1:{port}/v2/integration/fixture/blobs/"
    if phase == "initial":
        with http(base + "uploads/", data=b"", method="POST") as response:
            location = response.headers["Location"]
        location = urllib.parse.urljoin(base, location)
        with http(location + ("&" if "?" in location else "?") + "digest=" + digest, data=body, method="PUT") as response:
            require(response.status == 201, "Registry did not store blob")
    with http(base + digest) as response:
        require(response.read() == body, "Registry blob missing or changed")


def libvirt():
    xml = STATE / "domain.xml"
    xml.write_text("<domain type='qemu'><name>integration-fixture</name><memory unit='MiB'>128</memory>"
                   "<vcpu>1</vcpu><os><type arch='x86_64'>hvm</type></os><devices/></domain>\n")
    command("virsh", "-c", "qemu:///system", "define", str(xml))
    try:
        command("virsh", "-c", "qemu:///system", "start", "integration-fixture", "--paused")
        require(command("virsh", "-c", "qemu:///system", "domstate", "integration-fixture") == "paused", "VM not paused")
        command("virsh", "-c", "qemu:///system", "resume", "integration-fixture")
        require(command("virsh", "-c", "qemu:///system", "domstate", "integration-fixture") == "running", "VM not running")
    finally:
        command("virsh", "-c", "qemu:///system", "destroy", "integration-fixture", check=False)
        command("virsh", "-c", "qemu:///system", "undefine", "integration-fixture", check=False)


def nas(phase):
    case("all data mounts use fixture Btrfs disks and media identities", storage)
    for unit in ("nfs-server.service", "virtlogd.socket", "virtlockd.socket",
                 "nftables.service", "btrfs-backup.timer", "cockpit.service", "registry.service", "jellyfin.service",
                 "nut-server.service", "nut-monitor.service"):
        case(unit, lambda unit=unit: eventually(lambda: active(unit)))
    case("NAS policy applies at boot", lambda: eventually(lambda: oneshot("infrastructure-policy.service")))
    case("NUT reports synthetic UPS status through real driver and server",
         lambda: eventually(lambda: require(command("upsc", "lab@localhost", "ups.status") == "OL", "Unexpected UPS status")))
    case("NFS reads, root squash, phone-upload identity and read-only originals", nfs)
    case("Btrfs snapshots, incremental transfer, retention, restore and failure retry", lambda: backups(phase))
    case("registry blob round-trip and persistence", lambda: eventually(lambda: registry(phase)))
    case("Cockpit HTTPS responds", lambda: command("curl", "--fail", "--silent", "--insecure", "--max-time", "20", "https://127.0.0.1/"))
    case("Jellyfin health endpoint", lambda: require(command("curl", "--fail", "--silent", "--max-time", "20", "http://127.0.0.1:8096/health") == "Healthy", "Jellyfin is unhealthy"))
    case("libvirt starts, resumes and removes a real disposable QEMU domain", libvirt)
    skip("physical disks, UPS power loss and wake-on-LAN", "Synthetic SATA/USB disks and NUT dummy-ups; no RAID, SMART, power-cut or physical NIC validation")
    skip("application guest VMs and Caddy", "This suite tests the NAS image and its local services; Minecraft/Immich/Jellyfin guest workloads and K3s are not booted")


def unexpected_failures(profile):
    allowed = {"wake-on-lan.service", "clamav-freshclam.service", "suricata-update.service",
               "rpm-ostree-upgrade.service", "fwupd-refresh.service"}
    if profile == "workstation":
        allowed |= {"chatgpt-install.service", "update-system-flatpaks.service"}
    else:
        allowed.add("mdmonitor.service")  # The lab deliberately has no physical RAID arrays.
    units = command("systemctl", "--failed", "--no-legend", "--plain", "--no-pager").splitlines()
    unexpected = [line for line in units if line.split()[0] not in allowed]
    require(not unexpected, "Unexpected failed units:\n" + "\n".join(unexpected))


def main():
    global STARTUP_DEADLINE
    profile, phase = sys.argv[1:]
    require(profile in ("nas", "workstation") and phase in ("initial", "reboot"), "Invalid test phase")
    require((STATE / "profile").read_text().strip() == profile, "Not an instrumented test VM")
    require("integration-os" in command("lsblk", "-dn", "-o", "SERIAL"), "Refusing to run outside the disposable VM")
    # Isolate test NFS mounts, so cleanup cannot propagate to the host mount tree.
    if "--private" not in os.environ.get("INFRA_TEST_NAMESPACE", ""):
        env = dict(os.environ, INFRA_TEST_NAMESPACE="--private")
        result = subprocess.run(["unshare", "--mount", "--propagation", "private", sys.executable, __file__, profile, phase], env=env)
        return result.returncode
    STARTUP_DEADLINE = time.monotonic() + 180
    case("Ignition settings, encrypted root and persistent data", lambda: basic(profile, phase))
    case("installer preserves non-target disks", lambda: disks(profile))
    for unit in ("suricata.service", "clamd@scan.service", "clamav-clamonacc.service", "tuned.service"):
        case(unit, lambda unit=unit: eventually(lambda: active(unit)))
    case("gssproxy activates with its prepared state", lambda: command("systemctl", "start", "gssproxy.service"))
    for unit in ("clamav-prepare.service", "gssproxy-prepare.service"):
        case(unit, lambda unit=unit: eventually(lambda: oneshot(unit)))
    if phase == "initial":
        case("suricata-prepare.service", lambda: eventually(lambda: oneshot("suricata-prepare.service")))
    else:
        case("Suricata rule seed persists without reseeding", lambda: require(Path("/var/lib/suricata/rules/suricata.rules").stat().st_size > 0, "Empty rule seed"))
    case("clamd detects harmless EICAR test data", antivirus)
    case("Suricata accepts installed rules and configuration", lambda: command("suricata", "-T", "-c", "/etc/suricata/suricata.yaml", timeout=180))
    if profile == "nas":
        nas(phase)
    else:
        workstation(phase)
    case("no unexpected failed services", lambda: unexpected_failures(profile))
    skip("internet signature, rule, firmware and OS updates", "Deliberately isolated from external networks; seeded definitions and running engines are tested")
    print(json.dumps(RESULTS, indent=2))
    return 0  # Host consumes structured failures and sets the overall exit code.


if __name__ == "__main__":
    sys.exit(main())
