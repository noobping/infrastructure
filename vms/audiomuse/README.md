# AudioMuse-AI

A separate Fedora CoreOS VM provides local CPU music analysis for the **currently
authoritative** Jellyfin server. Deploying this role never starts the dedicated
Jellyfin VM, mounts its configuration, or changes the `music.vm` handover.
Deployment, publishing images and plugin installation are explicit operator steps.

## Architecture and versions

The existing VM base, signed OCI image pipeline, Butane fragments, Quadlets,
NAS socket activation and QEMU guest-agent idle reports are reused. Inventory
reserves `audiomuse.vm` / MAC `52:54:00:00:00:35`, 4 host-passthrough vCPUs,
12 GiB RAM and an 80 GiB local SSD-backed root disk, with autostart disabled.
The existing 4 CPU / 8 GiB Jellyfin guest cannot comfortably accommodate both
playback and upstream's 8 GiB analysis minimum. A separate guest also allows
analysis against the legacy NAS without touching shared Jellyfin configuration.
Budget these resources alongside existing guests before provisioning; inventory
does not establish that the physical NAS has enough free RAM.

Pinned upstream releases:

- [AudioMuse 3.6.3](https://github.com/NeptuneHub/AudioMuse-AI/tree/v3.6.3), CPU image,
  digest `301b2d5c280f43c6e79823337455b6b7d575d7b8040a6f150266804350c51eab`.
- PostgreSQL **15.18-alpine**, digest
  `3d0f7584ed7d04e27fa050d6683a74746608faf21f202be78460d679cc56461f`.
  Upstream explicitly targets PostgreSQL 15. Its task queue is in PostgreSQL;
  this release needs **no Redis**.
- [Jellyfin plugin 0.1.55.0](https://github.com/NeptuneHub/audiomuse-ai-plugin/tree/v0.1.55),
  ABI 10.11.0.0, for the repository's Jellyfin 10.11.11. The current plugin
  release targets Jellyfin 12 and must not replace this pin. The archive SHA256,
  source revision and manifest revision are recorded in
  [the plugin lock](../jellyfin/audiomuse-plugin.lock.json).

Web and worker containers run as UID 1009 with no capabilities, no privilege
escalation, read-only root filesystems, SELinux confinement and bounded CPU,
memory and processes. PostgreSQL runs as its image's UID 70. Health checks run
inside the awake VM; unhealthy services prevent idle shutdown. Systemd restarts
exited processes. Health failures alone deliberately do not kill an active
analysis or database; investigate failures rather than repeatedly aborting work.
The worker has no published ports; only web port 8000 is published. The database
is reachable only on the dedicated Podman bridge. Do not forward these ports
from the internet. The host firewall loads before Podman installs its rules.

Models/tokenizers ship in the digest-pinned application image and remain in
local Podman storage across reboot. No model download is needed during normal
inference. Persistent `audiomuse-web-state` and `audiomuse-worker-state` volumes
hold generated model/index caches, scratch audio and TLS state; the database
contains analyzed features, embeddings, settings, users and jobs. Do not mount
an old mutable model volume over `/app/model`: new release weights must match
its code. No GPU devices or CUDA are required. Upstream's GPU instructions
are NVIDIA-specific; this role does not claim AMD acceleration.

## Deployment and initial configuration

1. Reserve the guest hostname/MAC; point `discovery.vm` at the existing K3s/Caddy
   address. Keep `audiomuse.vm` pointing at the guest. Do not point it at the NAS.
2. Build/publish the NAS, VM base and AudioMuse role through the existing signed
   image pipeline. Review the rendered policy and Ignition before provisioning:
   `just online::_images stable amd64 audiomuse graph` uses the normal publication
   workflow; **run it only when ready to publish**. Create the guest with
   `sudo vm-deploy audiomuse`, then explicitly `sudo virsh start audiomuse`.
   Complete the initial rebase/reboot and existing signature-trust prerequisites.
3. Apply the new NAS backup export/directory definitions and verify
   `/var/lib/containers/audiomuse/backups` is UID/GID 1009, mode 0700, backed by the
   existing `apps` Btrfs subvolume. Never place live PostgreSQL data on NFS.
4. On the authoritative Jellyfin instance, create a dedicated non-administrator
   music user with access only to music, audio playback and playlist creation.
   **Disable media deletion and library administration** for that user. Prefer
   a user access token obtained by signing in as that user; dashboard API keys
   have wider permissions. Keep originals unchanged and do not enable metadata
   saving into music directories. AudioMuse has no music filesystem mount and
   reads downloads through Jellyfin; its only intended Jellyfin writes are playlists.
5. In the AudioMuse guest, create `/var/lib/audiomuse/jellyfin.env`, root:root,
   mode 0600 (parent mode 0700), with the actual values below. Use a protected
   editor or secret-transfer channel, not shell history or committed Ignition:

   ```ini
   JELLYFIN_URL=http://nas.vm:8096
   JELLYFIN_USER_ID=actual-user-id
   JELLYFIN_TOKEN=actual-user-access-token
   ```

   The legacy NAS remains the target until explicit handover. Its mutable
   `latest` tag does **not** prove which Jellyfin version is actually running.
   Check Dashboard / System info before installing the plugin. Do not upgrade
   or start the dedicated Jellyfin VM as part of this setup.

6. `audiomuse-prepare.service` generates unique database, administrator, API and
   session secrets once in `/var/lib/audiomuse/{database,auth}.env`, mode 0600.
   It refuses to generate a new password for an existing PostgreSQL volume.
   Missing/unsafe Jellyfin settings prevent web and worker startup: upstream's
   unauthenticated initial setup wizard must not be exposed on the LAN.
   After installing the file, run:

   ```sh
   sudo systemctl restart audiomuse-web.service audiomuse-worker.service
   sudo systemctl status audiomuse-database.service audiomuse-web.service audiomuse-worker.service
   ```

7. Before enabling the listener, check locally that `/api/setup` and `/api/config`
   reject requests without credentials, and that an authenticated request works.
   Check container logs for successful default-server import and admin creation.
   Then `sudo vm-on-demand enable audiomuse` on the NAS. Apply the `discovery.vm`
   Caddy route and its egress rule only after the listener is ready.
8. Visit `https://discovery.vm`, trusting the existing Caddy local CA. Read the
   generated `admin` password securely from `auth.env` and log in. In Setup Wizard
   confirm the Jellyfin server, user and music library. Keep Authentication on,
   the AI naming provider **NONE**, CLAP on, Lyrics off and external lyric APIs
   off. These defaults are seeded from `local.env` on the first database startup;
   subsequent changes are stored in the database and take precedence over env.
   Do not disable authentication or remove the last/default media server on an
   exposed installation: upstream then re-enters its initial setup flow.

`discovery.vm` provides browser TLS and bearer authentication for plugin calls.
Caddy-to-NAS-to-guest HTTP and the legacy Jellyfin API use the existing trusted
private LAN, like the repository's other wake routes. They are not encrypted
on that segment; an untrusted LAN needs a separate TLS transport rollout.
No public port forwarding is configured. Never add active health monitoring to
`discovery.vm` or NAS port 18000: that would wake sleeping guests.

## Jellyfin plugin

Take a Jellyfin configuration backup and acquire any applicable NAS maintenance
hold before installing. Run the opt-in helper **on the authoritative host**, from
this checkout (copy the helper and adjacent lock together if necessary):

```sh
sudo python3 vms/jellyfin/install-audiomuse-plugin \
  --config /var/lib/containers/jellyfin
```

For the dedicated guest after an independently approved handover, use the actual
mounted config volume path instead. The helper requires the already-running
local Jellyfin service and checks `/System/Info/Public` for exactly 10.11.11.
It downloads and verifies the locked archive before interrupting the service,
then installs only its new version directory as UID 1001, and restarts that same
service. It neither provisions nor starts VMs. Existing AudioMuse versions cause
a refusal; an identical installation is a no-op. Existing libraries, metadata,
other plugins and plugin configuration are left intact. Confirm the supplied
config path is the active service's configuration and never run the other instance.

Install the Caddy root certificate as a trusted CA on that Jellyfin host through
the normal host trust store. The new Quadlet drop-in mounts the host's extracted
CA bundle read-only into the Jellyfin container; reload Quadlets and restart the
active Jellyfin service after trust changes. Do not bypass certificate validation.
In Dashboard > Plugins > AudioMuse AI set:

- Backend URL: `https://discovery.vm`.
- API token: the `API_TOKEN` from AudioMuse `auth.env` (or the current value if
  changed through Setup Wizard).

Disable the plugin's default overnight scheduled tasks, or reschedule them to
NAS powered-on hours. Its Instant Mix and compatible clients call AudioMuse
on demand. Genre-only mixes bypass sonic analysis; insufficient similarity
results can fall back to Jellyfin metadata/random selections. Use AudioMuse's
similarity view to verify actual sonic matches. Plugin 0.1.55 has no multi-server
selector: configure this Jellyfin as AudioMuse's default server.

Do not subscribe this pin to automatic catalog updates. For updates, review the
Jellyfin ABI, artifact checksum and backend API together; update the lock and
container pins, repeat tests, take backups, and install the new version explicitly.

## First analysis and workouts

Open Analysis and Clustering, select a small album batch and start analysis.
Watch worker logs and the task list. Confirm tempo (BPM), energy, moods, audio
and CLAP embeddings before processing the whole library. All these models run
locally on CPU. Initial analysis can take hours or days; leave adequate disk
headroom for downloaded temporary audio, image updates and the database. Increase
worker memory only after measuring; limits can fail very large clustering jobs.

Use **Text Search** for sound descriptions such as “high energy workout music”,
“aggressive electronic music with strong bass”, “fast Japanese pop for cardio”,
or “powerful motivational heavy metal”. CLAP ranks sound/text similarity; it is
not a language detector, a BPM guarantee or an unrestricted conversational agent.
Inspect BPM and energy and audition the results. Double/half-time BPM detection
is common in drum & bass and hardstyle. J-pop/K-pop descriptions are approximate;
exact language selection may need library metadata in addition to sonic search.

Use Similar Songs for a seed track, then Song Alchemy's add/subtract examples
and its mood anchors to refine the sound; inspect the resulting tracks'
energy and tempo before saving. “Similar but more
energetic” is a workflow, not a promised compound natural-language constraint.
Text Search, similarity results and clustering playlists can be saved/exported
back to Jellyfin and played with existing clients. Cluster sonic neighbors for
recurring workout discovery; use the built-in clustering scheduler or the plugin's
clustering task to regenerate playlists during an awake session. Sonic Fingerprint
uses listening history for collection-based recommendations.

The **Instant Chat Playlist** feature needs an LLM provider. It remains disabled
with provider NONE; there is no Ollama or cloud model dependency. Saved playlists
are Jellyfin playlists, not automatically live-updating rule queries. Schedule
re-analysis and clustering explicitly; don't promise that a saved text query will
continually update itself. Available features are from the
[upstream algorithm](https://github.com/NeptuneHub/AudioMuse-AI/blob/v3.6.3/docs/ALGORITHM.md)
and [plugin behavior](https://github.com/NeptuneHub/audiomuse-ai-plugin/tree/v0.1.55).

## On-demand lifecycle and NAS power

NAS port 18000 wakes only AudioMuse. Local health/idle probes do not call any
Jellyfin endpoint. The guest checks all task rows, including queued/delayed
children, running jobs and hidden control/migration work, plus SQL transactions,
vacuum/index work, connections, upgrades and persistent backup/restore markers.
Missing schema, unknown status, failed health or inaccessible services fail closed.
Terminal SUCCESS/FAIL/REVOKED history alone does not keep the guest awake. Once
idle, the existing controller requires a fresh 30-minute quiet interval.

The NAS's nightly shutdown service now waits until 21:30 and defers physical
poweroff while the AudioMuse domain exists in any state other than `shut off`,
while any persistent VM hold exists, or while the NAS snapshot service is active.
The existing idle controller must shut down AudioMuse normally first. Unknown
libvirt/backup state also defers poweroff. No guest is woken by this check. This
can deliberately keep the NAS on overnight for long analyses or failed probes.

For an existing NAS installing the new image, cancel any already-reserved
shutdown with `sudo shutdown -c`, reload systemd and restart
`nightly-shutdown.service` **before the first analysis**. An already scheduled
legacy shutdown is not removed merely by replacing the unit. Confirm its new
ExecStart uses `vm-on-demand nightly`. Manual poweroff, forced shutdown, power
loss and UPS emergencies are outside the idle controller's protection.

Schedules inside sleeping guests cannot run. For unattended jobs, arrange a NAS
timer to wake AudioMuse and, after handover, Jellyfin during powered-on hours, then
let the application schedules enqueue the work. Until configured, run jobs while
awake. After handover change the default media-server URL in Setup Wizard to
`http://nas.vm:18096` so future Jellyfin requests wake it. Do not use its direct
sleeping guest address. The legacy URL must not be changed before handover.

## Backup and restoration

Follow the [shared NAS backup order](../README.md#safety-and-backups): acquire a
persistent NAS `vm-on-demand hold audiomuse`, then run the guest
`/usr/libexec/infrastructure/backup-prepare`. This takes a transactionally
consistent **online pg_dump**, verifies its archive directory, and atomically
writes `audiomuse.tar` to the root-squashed NFS backup export. It does not stop
analysis. The bundle includes database, admin/API/session and Jellyfin secrets.
It is mode 0600 under a 0700 directory; keep NAS snapshots equally restricted.

Run the NAS Btrfs snapshot service, then the guest `backup-finish`, then release
the NAS hold. Failure leaves the persistent `prepared` marker/hold for recovery.
A failed dump/transfer cannot replace the previous good archive. NFS uses a hard
named volume and cannot silently fall back to a guest-local directory. An NFS
outage can block transfer indefinitely; restore NAS service before retrying or
releasing holds. The weekly NAS snapshot alone cannot back up a live local database;
run prepare before it when an up-to-date logical backup is required.

Restore to a **fresh, isolated AudioMuse guest/database first**:

1. Hold the VM; create
   `/var/lib/infrastructure/backup/audiomuse/restoring` (root:root 0600). Stop web
   and worker. Keep the original database/VM intact; never restore over it.
2. Extract the trusted backup bundle into a root-only staging directory; verify
   `pg_restore --list` against `audiomuse.dump`. Restore the three `.env` files
   into `/var/lib/audiomuse`, mode 0600, **before initializing the fresh PostgreSQL
   volume**. They must match the restored application secrets.
3. Start only `audiomuse-database.service` with an empty local volume and run:

   ```sh
   sudo podman exec -i audiomuse-database pg_restore -U audiomuse -d audiomusedb \
     --single-transaction --exit-on-error --no-owner --no-acl < audiomuse.dump
   ```

4. Keep restored workers stopped until reviewing `task_status`: an online dump
   may contain NEW/RUNNING work that the upstream recovery mechanism will retry.
   On the isolated recovery copy, mark unfinished jobs REVOKED using the terminal
   state schema for the pinned release if they must not resume. Do not trigger
   duplicate playlist writes against the production Jellyfin during a restore drill.
5. Remove disposable model/index caches only if rebuilding is needed; the pinned
   image carries model weights and the database holds durable embeddings. Remove
   the `restoring` marker only after validation, start web/worker, verify login,
   features, Jellyfin connectivity and a small playlist, then release the hold.

The installer/plugin configuration belongs to the existing Jellyfin backup.
The AudioMuse backup does not replace it or copy originals. Root-disk snapshots
must be taken with the VM shut down or separately quiesced; do not copy live qcow2.
Before an upgrade, take a verified logical backup. An OCI rollback does not undo
schema/model changes: restore the matching pre-upgrade database into a separate
volume when downgrading. Review upstream release notes for re-analysis needs.

## Validation and troubleshooting

`just check-vm` covers credentials, backup failure/lock handling, NFS failure
contracts, Quadlet generation, plugin ABI pins,
create-only provisioning, idle decisions and NAS poweroff holds. `just check-online`
checks the online/offline/CI role selection and inventory-driven Ignition paths.
For real container tests, pull the three locked images, then run
`python3 vms/audiomuse/test/runtime`. It creates disposable containers, volumes
and synthetic audio, downloads the checksum-verified plugin and exercises
Jellyfin/plugin/API startup, CPU analysis on an internal network, authentication,
queue states, restart/container-replacement persistence and PostgreSQL restore. It never uses production
music, credentials or servers. Real Butane validation uses the same image tools
as the normal image pipeline.

Inspect `journalctl -u audiomuse-*.service`, `podman logs audiomuse-worker` and
`/run/vm-on-demand/idle.json`. Setup-required responses mean incomplete default
media-server settings, not permission to turn authentication off. A healthy empty
installation has no similarity index until analysis completes. A guest that never
sleeps may have a pending task, failed health check, SSH session, backup marker,
maintenance hold or active client. Fix the cause; do not delete queued work just
to force idle. For NFS problems check export ownership, DNS, `findmnt` and SELinux
AVCs; preserve enforcement. Never use label-disable as a workaround.

Deployment still requires DNS, CA trust, signature trust, production credentials,
capacity confirmation and schedule choices. Disposable container tests do not
validate live NAS NFS, physical power behavior, FCOS reboot, guest-agent SELinux
policy, real-library performance or production hardware. The local test host
reports SELinux Disabled; enforcing-guest validation remains required. Validate those during an
approved rollout before relying on unattended operation.
