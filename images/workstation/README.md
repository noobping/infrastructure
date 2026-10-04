# Workstation

Build the bootable image as part of the repository graph:

```sh
just offline workstation amd64
```

Boot the installer in a persistent AMD64 test VM:

```sh
just vm workstation
# Test the online installer instead:
just vm workstation online
```

The first run creates a 64 GiB sparse disk and starts the installer. Later runs
boot that disk and keep the ISO attached for the offline image rebase. The VM
has 8 GiB RAM, four CPUs, UEFI, and a persistent virtual TPM for disk encryption.
Offline VMs have networking disabled; online VMs use QEMU user networking.
The graphical window opens on the host, and the guest uses the same account
configuration as a physical workstation installation.

Install host QEMU, `swtpm`, and UEFI firmware (`edk2-ovmf` on Fedora). Run Just
on the host so it can access KVM and the display. VM disks, firmware, and TPM
state live together under `dist/vm/`; keep all three to retain access to the
encrypted installation. Shut down from inside the guest when finished.

`VM_MEMORY` (MiB), `VM_CPUS`, and `VM_DISK_SIZE` override the defaults; disk size
only applies to new VMs. Set `VM_NETWORK=user` to enable networking on the same
offline VM, or `VM_DISPLAY=none` for a headless run. `VM_ISO` selects a custom
installer. For a fresh installation without replacing the existing VM:

```sh
VM_NAME=workstation-test2 just vm-install workstation
```

Build and publish the image and its parents, then create an online installer:

```sh
PUBLISH=true just online::workstation amd64
PUBLISH=true pipeline online-workstation
```

The Pipeline command defaults to the native architecture. Set
`BUILD_ARCHITECTURE=amd64`, `arm64`, or `both` to override it. Online installers
are written to `dist/online/iso/` and download the image during installation.

At boot, `infrastructure-policy.service` applies local home ownership, missing
`/etc/skel` files, and `/etc/ups/netclient.env` as a NUT client configuration.
The embedded policy rootfs is updated and rolled back with this image.

```sh
sudo systemctl start infrastructure-policy.service
sudo journalctl -u infrastructure-policy.service -b
```

`chatgpt-install.service` downloads the architecture-matched ChatGPT Linux RPM
directly from OpenAI on first boot. The RPM is not redistributed in the public
image. The installer pins an immutable release URL, verifies its SHA-256 and
OpenAI signature, then stages it with rpm-ostree. It applies a fresh install
live when possible; an existing pending deployment or a version replacement
takes effect after reboot. Sway inherits the same service.

```sh
sudo systemctl status chatgpt-install.service
sudo journalctl -u chatgpt-install.service -b
chatgpt
```

To update the bootstrap release, change the version, both URLs, and both hashes
in `chatgpt-release.env` together.

IPS remains a native host service. A quick health check is:

```sh
sudo systemctl status suricata.service
sudo systemctl status suricata-update.timer
sudo nft list ruleset | grep -E 'SURICATA_HOST|queue num 0'
```
