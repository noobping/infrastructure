# Workstation

Build the bootable image as part of the repository graph:

```sh
just offline workstation amd64
```

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
