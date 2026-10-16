# Audio CD ripper

A standalone Fedora container shared by the NAS and Jellyfin VM. It extracts
pure audio CDs from the USB ASUS BW-16D1HT at `/dev/sr0`, writes lossless FLACs
to `/srv/music/cds/{artist}/{album}`, then automatically ejects successful
imports and verified duplicates. There is no enable file. The installed timer
checks udev every ten seconds when the drive exists, including discs present
at boot. Data CDs, mixed-mode CDs, DVDs, Blu-rays and other drives are ignored.

## Build and publishing

The container lives in `images/audio-cd-rip`, independently of the NAS image.
It uses the same build, architecture tags, run-scoped tags, manifest promotion
and signing pipeline as the other images. NAS and Jellyfin image builds first
build this dependency, copy its small host integration bundle, and set their
Quadlets to the **same build tag**. They do not embed its runtime filesystem.
The base follows `registry.fedoraproject.org/fedora:latest`, matching the policy
image's convention. `FEDORA_VERSION` is a build argument for selecting a release
when needed. Fedora release and package updates are resolved at build time;
CI exercises the resulting runtime before publication.

Build and publish just this container into the existing local build registry:

```sh
IMAGE_NAMESPACE=localhost:5000/noobping just online::stable audio-cd-rip amd64
# With native ARM64 or configured QEMU/binfmt support:
IMAGE_NAMESPACE=localhost:5000/noobping just online::stable audio-cd-rip both
```

The local registry must be running, as for the other online image builds.
The offline NAS/full graph also builds and publishes this dependency locally.
GitHub Actions builds AMD64 and ARM64, then publishes
`ghcr.io/noobping/audio-cd-rip:latest` through its existing authenticated
workflow. GitLab uses its configured registry. No separate credentials or
secrets are added. `just online::stable jellyfin amd64` builds the guest and
its dependencies; supply `IMAGE_NAMESPACE` for a local registry as above.

On first use the Quadlet pulls its selected image (`Pull=missing`). Cached
images work without registry access; metadata can fall back to Unknown tags.
Pre-pull that exact image before using an offline host. An offline OS installer
does not itself preload this separate application image into Podman storage.
There is no auto-update or image replacement during a rip.

## Storage and Jellyfin

On FCOS `/srv` points to `/var/srv`. The NAS ripper binds only
`/var/srv/music/cds` as `/music`, with UID/GID `1001:1001`, matching the existing
music account and Jellyfin container. The host helper requires the actual music
filesystem to be mounted so the existing `nofail` mount cannot redirect writes
onto the OS disk. It creates `cds/` with that ownership if absent. Existing
ownership is checked, never recursively changed.

```text
/srv/music/cds/
  Album Artist/
    Album/
      01 - Track title.flac
      cover.jpg                         # or cover.png, when available
      metadata.json
      .rip-manifest.json
  .state/                               # ignored by Jellyfin; back this up
  .work/                                # ignored staging and recovery files
```

`artist` is the album artist. Multi-disc releases share the album directory,
using filenames such as `01-01 - Title.flac` and `02-01 - Title.flac`, plus disc
number/total tags. A later disc is merged only for the same verified MusicBrainz
release and a new disc number. Different releases sharing a directory name,
unmanaged albums and edited files require manual resolution. Names are
sanitized and bounded. Unknown releases use `Unknown Artist/Unknown Album
[TOC hash]` to avoid collisions; normal album paths have no IDs or disc folders.

The approved NFS export grants **only `jellyfin.vm`** writable, root-squashed
access to `/var/srv/music/cds`, with `subtree_check` to constrain that writable
subdirectory export. See [exports(5)](https://www.man7.org/linux/man-pages/man5/exports.5.html)
for the subtree security and rename tradeoff. The VM's ripper pulls in
`var-srv-music-cds.mount` on demand, verifies the mount and numeric ownership,
and uses the same shared state and files as the NAS. The normal Jellyfin music
volume remains read-only. `audio-cd-storage.service` prepares the NAS directory
before the NFS export view is built. No live exports are changed by editing or
building this repository.

Jellyfin already mounts the parent music library as `/music`. Confirm its Music
library includes `/music` or `/music/cds`, and retain a scheduled **Scan Media
Library** task. NAS real-time monitoring can detect new files; for NFS use
scheduled scans or **Scan Library** after waking the VM. No API token is needed.
The ripper does not wake a sleeping Jellyfin VM or migrate its configuration.
See [Jellyfin's music layout](https://jellyfin.org/docs/general/server/media/music/).

## Extraction, metadata and recovery

- `cdparanoia` uses default full paranoia with `-X` (abort on skipped reads).
  PCM must match the TOC sector count, stereo, 16-bit and 44.1 kHz. FLAC uses
  `--verify`, followed by `flac --test` after tagging. No lossy intermediate.
  This does not implement AccurateRip, drive offset correction, de-emphasis,
  or hidden track-one pregap extraction. See the
  [cdparanoia manual](https://www.xiph.org/paranoia/manual.html).
- MusicBrainz exact disc-ID lookup applies only a unique release match, with
  bounded HTTPS requests, retries and rate limiting. Cover Art Archive front
  artwork is embedded and saved beside the tracks. Missing metadata, ambiguous
  releases or network outages still allow a rip with Unknown tags. Candidate
  IDs, TOC and lookup results remain in `metadata.json` (disc-prefixed for sets).
- Fully verified tracks are staged in `.work/`. NAS and VM both publish them
  with no-overwrite hard links, then atomically update the album manifest.
  Only the new disc is staged; existing album files stay in place. A journal
  permits interrupted publication to resume. A scan during publication can
  briefly see part of the track list, but never a partial FLAC.
- `.state/discs/` stores pending/completed transactions; a repeated TOC verifies
  every album file hash before skipping extraction. A pending transaction can
  finish publication without rereading audio. Changed, missing or conflicting
  completed files cause failure, never overwrite. TOC IDs are not audio
  fingerprints; rare equal-TOC discs need manual handling.
- A shared POSIX file lock serializes NAS and NFS client writers. Linux `DISKSEQ`
  distinguishes insertions. Failed jobs are attempted once per insertion;
  reinsertion, reboot or explicit retry permits another attempt. Disc identity
  is rechecked before tracks, publication and eject.
- The tray is locked during work, then unlocked. Success or a verified duplicate
  ejects automatically. Errors keep the disc loaded and retain work/logs.
  Eject failure is reported without invalidating a completed import. Each read
  has a 30-minute limit, and the service a three-hour limit.
- The NAS nightly shutdown controller waits for its ripper and for a running
  Jellyfin VM. The guest's idle report stays busy during ripping, protecting
  the NFS writer from automatic guest shutdown. Manual poweroff or power loss
  still requires recovery. Do not use another player/ripper on the same drive.

Both hidden directories contain empty `.ignore` files for
[Jellyfin exclusion](https://jellyfin.org/docs/general/server/media/excluding-directory/).
Per-disc staging files and failed attempts are retained, so monitor free space
and remove unneeded old work/logs only while no ripper is active. Back up
`.state/` with the music; it is also used when switching between NAS and VM.

## Permissions and rollout

The system Quadlet drops all capabilities, uses a read-only root and
no-new-privileges, and limits CPU, memory and processes. Only `/dev/sr0:rw` is
passed through. Supplementary `cdrom` group access (Fedora GID 11) and the
ASUS-specific udev rule's `0660` mode avoid the earlier Toolbox permission
failure. No privileged mode, raw SCSI devices, host network or Podman socket
is granted. Configuration is read-only; only `cds/` is writable.

As in the existing NAS media deployment, `SecurityLabelDisable=true` disables
SELinux separation for this container only. Host enforcement remains enabled;
there is no recursive relabel or additional global boolean. The VM retains
its existing NFS SELinux service. DAC, device cgroups, dropped capabilities and
seccomp still apply. Physical USB/SELinux behavior needs a first-disc check.

1. Build and deploy the normal NAS and/or Jellyfin VM images using the existing
   rollout and planned reboot. Deploy the NAS export change before guest use.
   Check that the music filesystem is mounted and an existing `cds/` directory
   is owned by `1001:1001`; resolve ownership conflicts deliberately. The timer
   starts automatically and needs no enable file.
2. For guest ripping, pass the USB optical drive through to **only that VM** so
   it appears as `/dev/sr0` with `ID_BUS=usb` and model containing `BW-16D1HT`.
   This repository does not add USB passthrough without the enclosure's actual
   identity. Stop NAS ripping before transferring the drive. The VM must be
   running, able to reach `nas.vm`, and have the normal NFS/UID configuration.
3. Ensure the Quadlet's image is reachable or pre-pulled. Insert an ordinary CD
   and follow `journalctl -fu audio-cd-rip.service`. Confirm ejection, track
   count, tags and playback after Jellyfin's scan; reinsert to check duplicates.
   Check an unreadable disc and a data CD before unattended use.

The live NAS was not inspected or deployed as part of this implementation.
Builds and fixtures cannot validate the USB bridge, real disc reads, live NFS
permissions or Jellyfin's configured library/scanning settings.

## Operations

Summaries go to the journal; command logs and errors live in
`/srv/music/cds/.state/logs/<attempt>/`. Failed work remains in `.work/`.

```sh
sudo journalctl -u audio-cd-rip.service -u audio-cd-detect.service -b
sudo /usr/libexec/infrastructure/audio-cd-dispatch retry

# Maintenance; run on both machines if either can access the drive.
sudo systemctl mask --now audio-cd-detect.timer audio-cd-rip.service
sudo systemctl unmask audio-cd-detect.timer audio-cd-rip.service
sudo systemctl start audio-cd-detect.timer
```

If a hard kill or USB failure leaves the tray locked, stop the service before
using `eject -i off /dev/sr0` and `eject /dev/sr0` from an environment containing
util-linux with appropriate device access. Inspect AVCs for permission errors
instead of granting privileged mode.

Before a first import, an ambiguous release can be resolved in
`/etc/audio-cd-rip/overrides.json`, mapping the logged disc ID to a MusicBrainz
release UUID. This file contains no secrets. An override must validate against
the actual disc. It does not retag an already completed import. Manually retagged
albums change hashes; reconcile their manifest and completion record rather
than deleting state to force an overwrite.

## Validation

```sh
just check-audio-cd
just test-audio-cd-runtime
just check-quadlets
```

Fixtures cover metadata/artwork, real FLAC tags and PCM, duplicate checks,
errors and eject, absent mounts, symlinks, interruption recovery, NFS publication,
shared locking, multi-disc merging and shutdown guards. Full `pipeline check`
also validates build selection and the pinned FCOS Quadlet generator, including
the VM's effective drop-in. No test needs live NAS access or an optical disc.
