# Local VM integration tests

These opt-in tests boot the actual offline installer, install onto a blank disk,
wait for its production image rebase, check the running system, reboot it, and
check persistent settings and data. A failed assertion or timeout returns a
nonzero exit code. They are separate from the fast `just check-vm` tests and
commit hooks.

```sh
# Build the exact images/media you want to test; skip if already built.
just offline nas amd64
just offline workstation amd64

just test-vms-preflight
just test-vm nas --pull
just test-vm workstation
# Both profiles, sequentially:
just test-vms --pull
```

`pipeline test-vms` runs the same suite, requiring cached application images.
Tests use the existing ISO in `dist/iso`; they do not rebuild it. After changing
image or installer configuration, rebuild with `just offline nas amd64` (or the
matching profile) before testing. `--pull` does not update the NAS operating
system image embedded in that ISO.

`--pull` lets the host fetch the NAS application images named in the **installed
image's** Quadlets and stream them into the test VM. Without it, those references
must already exist in the host Podman cache. References, IDs and available
repository digests are recorded in the report. The guest has no external network,
so installation, the image rebase, Flatpak initialization and seeded security
services really must work offline. This does not test internet update delivery.

For a quicker image check before booting a VM, run
`just test-ips-policy IMAGE` against a locally built IPS, NAS or Workstation
image. It exercises the embedded policy runtime with actual seed data and
checks that runtime mount targets already exist for the immutable `/usr` of a
booted system, before a writable extraction could hide missing files.
`just test-flatpak-cache IMAGE` validates a desktop image's bundled apps.

Run these on the development host. Required tools are Python 3.11+, Podman,
QEMU x86_64, qemu-img, swtpm, OpenSSH, and matching raw OVMF firmware. Podman uses
`quay.io/coreos/coreos-installer:release` to read and instrument the ISO. Firmware
can be selected with `VM_UEFI_CODE` and `VM_UEFI_VARS`. Default resources are four
vCPUs and 12 GiB RAM, one VM at a time. Allow at least 30 GiB free space per run;
failed or retained runs can consume more as services populate their storage.

KVM must be accessible to the current user. Without it, explicitly opt into slow
software emulation with `VM_TEST_ACCEL=tcg`. `VM_TEST_TIMEOUT` is the overall test
deadline in seconds (default 3600); `VM_TEST_MEMORY` is MiB and `VM_TEST_CPUS` sets
CPU count. For example:

```sh
VM_TEST_ACCEL=tcg VM_TEST_TIMEOUT=7200 just test-vm nas --pull
just test-vm workstation --keep
```

## Isolation and artifacts

Every invocation creates a private, uniquely named directory in
`dist/integration/`. QEMU uses only newly created files: a 64 GiB OS disk, 96 GiB
SSD, 128 GiB HDD and a smaller 1 GiB USB decoy. These are sparse virtual disks,
not physical host devices. The normal installer must select the smallest
non-USB disk; sentinel data verifies that the other disks survive installation.
The firmware and virtual TPM persist through reboots, exercising unattended
unlock of the encrypted root.

The network is isolated QEMU user networking: no bridge, outbound access, real
NAS connection or LAN listeners. SSH is forwarded to a random **loopback-only**
host port and uses a fresh key, with the user's SSH configuration disabled.
Commands and diagnostics use a separate private virtio serial channel, so a
broken firewall cannot hide guest failures. SSH connectivity through the actual
guest firewall is a separate required assertion; the diagnostic channel does
not make that assertion pass.
Tests never invoke the host's libvirt or deploy to `nas.vm`.

The source ISO is checksum-verified and copied, never modified in place. Its
original destination Ignition is kept intact as a merge source. The recorded
test overlay adds an ephemeral root SSH key, guest assertions, serial journal
forwarding, a private serial test agent and fixture preparation. On NAS it also supplies a dummy UPS,
loopback export-client names, and masks the clock-dependent nightly shutdown.
The real disk selector, installer, image rebase and signed-image policy are
preserved. Trust or rebase failures fail the suite; it never switches to an
unsigned image or writes the rebase completion marker on the installer's behalf.

Each run keeps `report.json`, `junit.xml`, deployment metadata, source ISO hash,
original/test Ignition, QEMU arguments, serial/guest journals, service/storage
diagnostics, and a screen capture when QMP is available. The Git revision in the
report identifies the **test checkout**, not necessarily the already-built ISO.
Rebuild before testing source changes. Logs and test keys are private to the user.

Successful runs remove their large disk/ISO files and private key unless `--keep`
is supplied. Failed runs retain them for inspection. QEMU and swtpm are stopped
on completion, error, interruption or timeout. Nothing autostarts afterward.
Remove old run directories yourself when no longer needed.

## Coverage

Both profiles test the real install/rebase, hostname, account UID, timezone,
encrypted root and TPM, SELinux enforcement, reboot persistence, seeded ClamAV
with the harmless standard EICAR string, Suricata configuration/rules, policy
preparation and unexpected failed services.

Workstation additionally checks GDM and the graphical boot target, effective
GNOME wallpaper/accent/locale settings as the real user, keyboard and login
configuration, home permissions and skeleton files, preservation of user changes
when policy reruns, all recommended offline Flatpaks, firewall, discovery,
printing sockets, cachefilesd and libvirt.

NAS additionally uses labeled Btrfs fixture disks and real PNG/document data:

- Every configured data mount must be on its intended fixture disk; an empty
  directory left on the OS disk is a failure.
- The real kernel NFS server/client exercise NFSv3/v4, existing exports, read-only
  photos, root squashing, UID 1005 uploads, artifact downloads and the nested
  music filesystem. Mounts are isolated in a private namespace. This tests local
  protocol and permissions, not routing/firewall traversal from another machine.
- Restart NFS while a real container is running, remove that container, and run
  the NAS policy twice. Removal must leave no container storage or retained
  shared-memory mounts in the export view.
- The production backup script snapshots photos/docs, performs incremental
  send/receive, prunes retention, restores a writable copy, and retries after an
  injected destination failure. It intentionally avoids copying all container
  storage. VM application backup hooks have separate tests in `check-vm`.
- The registry stores and retrieves a blob across reboot. Cockpit HTTPS and the
  local Jellyfin health endpoint must respond. Local Quadlets must be running.
- Libvirt defines, starts, pauses/resumes and deletes a real tiny QEMU domain.
  This is a hypervisor lifecycle check, not a nested installed guest test.
- Production NUT policy runs against its supported environment file with the
  [NUT dummy-ups driver](https://networkupstools.org/docs/man/dummy-ups.html), and
  the driver/server/monitor must expose an online synthetic UPS. The test-only
  shutdown command is harmless.

Reports explicitly skip physical RAID/SMART, real UPS power cuts, wake-on-LAN,
desktop interaction, GPU/peripherals and external updates. They also skip the
Minecraft, Immich and Jellyfin **guest workloads**, Caddy and K3s: those are
separate deployments, not services in the NAS image. K3s remains outside this
test rollout. This suite cannot establish that every home service works end to
end; it gives real installation and host-service evidence with those limits
visible in the report.

## Extending and checking the harness

Add assertions to `guest.py`, leaving production configuration in the image.
Use synthetic fixture inputs in `prepare-disks` or the documented Ignition
overlay instead of replacing production units with mocks. Fail required checks;
reserve skips for explicitly unsupported coverage. Run:

```sh
python3 -B test/integration/test_runner.py
just check-vm
just check-just
just test-vm nas --pull
just test-vm workstation
```

The fast harness tests check configuration preservation, disk/network isolation,
process cleanup, deadlines, KVM selection, and machine-readable failure/skip
reporting. They do not substitute for the real VM tests.
