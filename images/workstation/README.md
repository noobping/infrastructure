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

IPS remains a native host service. A quick health check is:

```sh
sudo systemctl status suricata.service
sudo systemctl status suricata-update.timer
sudo nft list ruleset | grep -E 'SURICATA_HOST|queue num 0'
```
