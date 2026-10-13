# Validation

Offline checks run through `just check-vm`; build selection checks run through
`just check-online`. `check.py` runs shell hooks with isolated command fixtures;
it does not assert live NFS behavior. The real Quadlet generator is used when
installed. The integration test is separate because it needs Podman and several
GB of images. Pull the image references from the new Quadlets and the pinned
Jellyfin Quadlet before running `python3 vms/audiomuse/test/runtime`.

The runtime test uses a disposable internal Podman network, new volumes, a
checksum-verified plugin download, and a synthetic 20-second WAV. It verifies:

- Plugin 0.1.55.0 loads as Active on Jellyfin 10.11.11 and forwards API requests.
- Jellyfin library scan, AudioMuse HTTP download and CPU analysis work without
  external container networking; tempo, energy and CLAP embeddings are stored.
- The non-admin Jellyfin account analyzes music; semantic workout search runs
  locally, the plugin exports a playlist, and Jellyfin streams the original bytes.
- Read-only music checksum is unchanged; web/worker/PostgreSQL run non-root under
  the deployed read-only/capability/resource restrictions.
- Configuration API rejects unauthenticated requests and accepts the bearer token.
- Completed jobs become idle with web/worker running. NEW, RUNNING and unknown
  states (including hidden control jobs) keep the database busy; terminal states
  do not. Missing database/schema fails the production probe.
- Database data and credentials survive restart and web-container replacement.
- A custom-format pg_dump restores transactionally into a separate database.

Validation performed locally on 2026-10-13:

- `just check-vm`: passed (including new backup, lifecycle and provisioning tests).
- `just check-online`, `just check-just`, `just check-shell`, `git diff --check`: passed.
- Butane `--strict` rendering and `ignition-validate` for the real AudioMuse
  fragment: passed with the repository's existing tool images.
- Local AMD64 role image build against the already-built VM base: passed.
- Quadlet generation and `systemd-analyze verify` in the built role image: passed.
  The inherited image emitted an unrelated pre-existing gssproxy
  `StateDirectoryMode=` warning; no AudioMuse unit errors were reported.
- Real runtime test described above: passed on AMD64 CPU, including resource limits.

The development host reports SELinux **Disabled**; container confinement on an
enforcing Fedora CoreOS guest has not been exercised. The new Quadlets do not
disable labeling or enforcement.

These checks do not boot a real Fedora CoreOS/libvirt guest, build the complete
NAS/base pipeline, test ARM64 runtime or production hardware, or exercise real
NAS NFS/SELinux exports and physical power schedules. Follow the deployment
runbook and the on-demand live validation checklist during an approved rollout.
