# Infrastructure Policy

This image converges a small, explicit set of host files without a privileged
container, host PID namespace, systemd socket, network, or host-root mount.

```sh
podman run --rm ghcr.io/noobping/policy:latest list
podman run --rm ghcr.io/noobping/policy:latest version
```

The bootc Workstation, Sway, and NAS images embed a pinned copy and expose it as
`infrastructure-policy.service`. That is the preferred way to apply policy on
those hosts:

```sh
sudo systemctl start infrastructure-policy.service
sudo journalctl -u infrastructure-policy.service -b
```

To check or apply the Workstation profile directly, use the same restricted
mounts and capabilities as the Quadlet. Replace `check` with `apply` to make
file changes. `check` returns 1 for drift and 2 for invalid policy input. On
the bootc hosts, prefer the systemd command above for `apply`; the Quadlet also
restores SELinux labels on the exact managed paths and restarts the native NUT
units after a successful run. Run a direct Workstation `apply` only during a
maintenance window with no active local-user sessions, because it converges
paths inside user-owned home directories.

```sh
sudo podman run --rm \
  --network none \
  --read-only --read-only-tmpfs \
  --security-opt no-new-privileges \
  --security-opt label=disable \
  --cap-drop all \
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
  --pids-limit 128 \
  -v /etc/passwd:/host/etc/passwd:ro \
  -v /etc/group:/host/etc/group:ro \
  -v /etc/skel:/host/etc/skel:ro \
  -v /etc/ups:/host/etc/ups:rw \
  -v /var/home:/host/var/home:rw \
  ghcr.io/noobping/policy:latest check workstation --root /host
```

The NAS profile needs only `/etc/passwd`, `/etc/group`, and `/etc/ups`. Sway is
an alias for Workstation and consumes the Sway image's `/etc/skel`. NUT secrets
remain in the host's `netclient.env` or `nut.env`; they are parsed as data and
are never copied into the image or printed in change logs.

The policy deliberately does not manage SELinux booleans, mounts, Btrfs,
backups, Flatpak, systemd itself, or operational containers. Those operations
remain in narrowly scoped native host units.
