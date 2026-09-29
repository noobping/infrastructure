# Infrastructure Policy

This image uses bundled Ansible roles to converge a small, explicit set of
host files without a privileged container, host PID namespace, systemd
socket, network, or host-root mount.

`ansible/site.yml` runs locally inside the container with fact gathering
disabled. The `homes` role manages home ownership and permissions; `skeleton`
adds missing skeleton entries while preserving existing user content and
modes; `nut` validates settings and renders the NUT templates. Only
`ansible-core` is needed: there are no Galaxy downloads or runtime Git pulls.

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

## Validation

The image build runs `test/fixture` against a disposable host tree. It checks
convergence, repeated applies, read-only drift checks, profile selection,
credential redaction, and rejected inputs and symlinks. To run it from a
checkout with ansible-core installed, use a disposable container as root
(the fixture exercises numeric ownership):

```sh
POLICY_BINARY="$PWD/images/policy/bin/infrastructure-policy" \
  bash images/policy/test/fixture
```
