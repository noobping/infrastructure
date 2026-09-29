# Infrastructure Policy

This image uses bundled Ansible roles to converge a small, explicit set of
host files without a privileged container, host PID namespace, systemd
socket, network, or host-root mount.

`ansible/site.yml` runs locally inside the container with fact gathering
disabled. The `homes` role manages home ownership and permissions; `skeleton`
adds missing skeleton entries while preserving existing user content and
modes; `nut` validates settings and renders the NUT templates. Only
`ansible-core` is needed: there are no Galaxy downloads or runtime Git pulls.

The `clamav`, `suricata`, and `gssproxy` profiles use
`ansible/service-state.yml` with declarative definitions under
`ansible/profiles/`. The shared `service_state` role manages directories,
numeric host ownership, permissions, missing seed files, and the gssproxy
socket compatibility link. Updated signatures and rules are preserved. A
read-only preflight rejects symlinks in recursive state/seed trees before
any task mutates them. Service profiles use native relabeling of their exact
mounted state roots instead of `--report-managed`.

The Python CLI preserves `apply`, `check`, `list`, `version`, profile aliases,
and the managed-path report consumed by the host units. `check` invokes
Ansible's check mode and translates its change count into exit status 1;
successful convergence returns 0 and invalid input or execution failures
return 2. Output names changed tasks; secret-bearing tasks suppress logs and
diffs. Repeated applies are silent when the host already matches policy.

A read-only `policy_inputs` module reads host UID/GID values and parses NUT
environment assignments as literal data. It validates paths before any
convergence task runs, resolving absolute host symlinks below the mounted
root and rejecting redirected homes, skeleton directories, and NUT files.
Like the previous implementation, preflight checks do not protect against
concurrent user renames: Workstation policy must run before user sessions or
during a maintenance window. SELinux relabeling and host service activation
remain in the existing native units.

```sh
podman run --rm ghcr.io/noobping/policy:latest list
podman run --rm ghcr.io/noobping/policy:latest version
```

The IPS base embeds the pinned runtime. Workstation, Sway, and NAS inherit it
and expose their main profile as `infrastructure-policy.service`. That is the
preferred way to apply the main policy on those hosts:

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

Service-state profiles have separate Quadlets with read-only host account
files and seed directories. Their writable mounts are limited to the
corresponding `/var/lib`, `/var/log`, and (for ClamAV) `/run/clamd.scan` roots.
Host tmpfiles rules create the mount roots and shared scan directories before
the containers start. SELinux labeling and the antivirus boolean are applied
by the native service after successful convergence. Run these preparation
services while their daemons are stopped, as at boot; preflight is not a
lock against a concurrently changing daemon-owned tree.

The policy deliberately does not manage SELinux booleans, mounts, Btrfs,
backups, Flatpak, systemd itself, or operational containers. Those operations
remain in narrowly scoped native host units.

## Validation

The image build runs `test/fixture` and `test/service-fixture` against
disposable host trees. They check
convergence, repeated applies, read-only drift checks, profile selection,
credential redaction, rejected inputs and symlinks, preservation of downloaded
data, and migration of a stale Unix socket. The repository test command also
runs both fixtures with no network, a read-only root, and the same three
capabilities as the production Quadlets:

```sh
just test-policy
```

`pipeline test-policy` runs the same recipe. Both CI providers exercise it on
native AMD64 and ARM64 runners. The fixtures validate file convergence and
container restrictions; a booted-host smoke test is still needed to validate
real daemon startup, SELinux enforcement, and the full systemd boot graph.
