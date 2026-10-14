# GitLab validation

Run the fast checks from the repository root:

```sh
just check-vm
just check-online
just check-just
just check-shell
```

`check.py` contains 25 tests for paired activation/draining, requests during
shutdown, post-drain report freshness, missing companions, nightly shutdown,
persistent holds, job and child-pipeline activity, Sidekiq/Runner evidence,
direct polling without wake activation, credentials, version-change guards,
failed NFS exports, certificate backup/restore, disk pressure, leftover containers
and sign-before-publish behavior. These tests
use isolated command fixtures for host operations and NFS; they never contact the
NAS. Existing NAS tests also exercise actual local TCP/UDP forwarding and a
disposable QEMU guest-agent socket. Hosted build graph tests retain both AMD64
and ARM64 coverage, with the two new roles added.

The separate runtime test requires rootless Podman, Buildah, Skopeo, Git,
ssh-keygen, Cosign 2.6.4 and the checksum-pinned AMD64 Runner 19.4.1 binary.
Place the Runner binary in `dist/gitlab-test/bin/gitlab-runner` or set
`GITLAB_TEST_RUNNER`. Download it from the URL in the worker Containerfile and
verify it against `vms/gitlab-runner/runner.sha256`. Put Cosign on `PATH`.
Allow at least 16 GiB spare RAM and ample disk space for the container and backups.

```sh
mkdir -p dist/gitlab-test
python3 vms/gitlab/test/runtime
```

The test creates a random container name, loopback-only ports, disposable
credentials and new storage under ignored `dist/gitlab-test/`. It uses HTTP and
explicit insecure-registry flags only for this loopback fixture; production
requires Caddy TLS and CA trust. The Runner executes trusted fixture code as the
invoking unprivileged account. It verifies:

- GitLab starts with the production memory/CPU/PID/capability restrictions.
- Authenticated HTTP clone/push and Git SSH access work.
- A protected project runner executes an actual shell job that builds an AMD64
  image, pushes it, signs/verifies it, and uploads package/artifact bytes.
- Local monitoring API endpoints accept the production queries.
- Application backup restores a deliberately changed database row, repositories,
  packages and artifact bytes.
- Configuration, encrypted signing variables, authenticated repository access,
  registry pull and signature verification survive restore and container
  recreation against persistent storage.

Normally the fixture removes its own container and files. Set `GITLAB_TEST_KEEP=1`
only for debugging; its private token, signing key and GitLab data then remain in
the ignored fixture directory. Remove that named container and directory after
inspection using rootless Podman's user namespace for subordinate-owned files.

## Results on 2026-10-14

- `just check-vm`, `just check-online`, `just check-just`, `just check-shell`,
  explicit syntax checks of new helpers and `git diff --check`: passed.
- Strict Butane rendering and Ignition validation for both merged role configs:
  passed using the repository's tool images.
- Native AMD64 VM base, GitLab and Runner image builds: passed.
- Actual Quadlet generation and `systemd-analyze verify` in the built role images:
  passed. The inherited gssproxy unit emits its existing `StateDirectoryMode=`
  warning; no GitLab/Runner dependency errors were reported.
- Rendered NAS socket/service dependency validation and Caddy config validation:
  passed.
- The self-hosted CI YAML passed the running GitLab server's own CI linter.
- The NFS writer's privilege drop and access through a root-only parent directory
  passed a disposable user-namespace test; the parent remained mode 0700.
- The disposable runtime scenarios above: passed. During development the restore
  and recreation assertions were continued against the same retained fixture
  after correcting the fixture; this was not one uninterrupted final harness run.
- Production GitLab idle logic was exercised against that live instance (only
  fixture addresses, container name and token location were substituted). The
  freshly started Runner's real metrics and the server both reported idle.

## Checks still needed during an approved rollout

The development host reports SELinux **Enforcing**, and the GitLab VM
frontend runtime test passed with SELinux enabled. An earlier Disabled result
was read inside a container and did not describe the host. No FCOS guest,
real libvirt VM boot/reboot, physical NAS power schedule or actual NFS export was
tested. The fixture uses the development host's unprivileged UID, not a booted
worker's UID 1011/systemd login session. Validate rootless user-service ordering,
SIGQUIT drain during guest shutdown, cgroup resource limits and CA trust there.

The entire 13-image local pipeline and installer publication were not run on the
new VMs; the real smoke job used a small scratch image. Offline tests validate the
full publication graph and failure paths. ARM64 build selection remains covered,
but new ARM64 role images/runtime were not built or executed locally.

Test actual NFS outage/recovery and Btrfs snapshot/restore on disposable NAS data,
then perform the documented matching-version GitLab restore drill. Container
recreation proves application persistence, not guest reboot or upgrade hardware
behavior. No production migration, deployment, signing-trust change, push or merge
was performed.

## Plug-and-play setup regression checks

`test/setup.py` adds twelve offline checks for Butane identity/password verification,
private atomic credential files, protected/idempotent project registration,
signing-key mismatch rejection, SSH host verification, secret-free command arguments,
CA validation, readiness after reconfiguration, temporary token cleanup,
VM-only certificate handling, direct Runner polling and protected NAS service ports. These run in
`just check-vm`. That recipe passes its exact Just executable into publication
tests, so Pipeline/editor hooks do not need `just` on `PATH`.

To reproduce the reported hook failure environment, invoke Just by its absolute
path with a system-only `PATH`; this passed after the fix. The tests no longer
pass `None` from `shutil.which('just')` to subprocess.

Two additional disposable runtime checks are available:

```sh
python3 vms/gitlab/test/frontend-runtime
python3 vms/gitlab/test/setup-runtime
```

The frontend test uses the pinned real Caddy image and its generated private CA,
with production non-root, read-only, capability, CPU, memory and PID restrictions.
It verifies actual Caddy listener configuration (8443 plus a loopback-only health
port, no 80/443), trusted HTTPS through a real socket-activated TCP relay,
rejection without CA trust, registry/browser/pipeline-trigger forwarding,
direct Runner API polling without relay activation, failed polling without wake
requests, and certificate persistence across a restart. No cluster service is
used. Independent availability sentinels remain reachable when the GitLab backend
and frontend stop; these are not real Cockpit, sshd or Jellyfin processes. The
actual FCOS NAS suite retains its Cockpit/SSH/Jellyfin checks. The corrected test
passed locally on 2026-10-14 under enforcing SELinux.

GitLab TLS now runs entirely inside the GitLab VM. The NAS has only encrypted
TCP forwarding on 8443 and Git SSH forwarding on 2222. Offline regression checks
verify setup does not stop/mask/restart the existing NAS services or activate a
Jellyfin migration. The NAS image no longer includes the GitLab frontend.
The VM base, NAS, GitLab and Runner AMD64 image rebuilds passed. Actual Quadlet
generation and systemd dependency validation passed for the VM frontend, GitLab
and Runner services in those images.
Generated Cockpit and Jellyfin units plus the native SSH unit validated together
in the built NAS image (`--man=no` skips manual pages absent from that image).
Only the existing gssproxy `StateDirectoryMode=` warning remained. No production
Cockpit/SSH/Jellyfin service or nightly power schedule was changed or exercised.

The certificate backup regression runs the production backup wrapper with
fixtures for the application dump, NFS and host commands. It restores a private
CA key and public certificate with their permissions from the completed bundle,
and verifies a missing CA aborts export while retaining the previous backup and
maintenance hold. This validates the archive procedure, not a real NFS server.

The setup test uses the pinned real GitLab image and Runner binary, exercising
Rails bootstrap, administrator password/key setup, read-only monitoring tokens,
private project/branch/tag configuration, protected signing variables, Runner
registration/verification and repeat setup. Host sudo/SSH/CA installation and real
VM startup remain separate rollout checks; the test substitutes fixture paths
and host-service operations instead of modifying the development machine.

These setup assertions passed locally on 2026-10-14 against the retained
disposable fixture after fixing GitLab's unprivileged Rails runner file access,
SSH-key creation through the supported API, and readiness after reconfiguration.
Both setup passes reused one project, runner and signing identity; the password
was valid and unexpired, and temporary setup tokens were revoked. This was a
continuation against the same fixture, not one uninterrupted fresh harness run.
The fixture and its private credentials were removed afterward.
