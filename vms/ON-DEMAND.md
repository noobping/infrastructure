# On-demand VMs

Minecraft, Immich, and Jellyfin wake on connections to NAS listening sockets.
After at least 30 minutes without client traffic or application work, the NAS
requests a graceful guest shutdown. K3s keeps its existing boot policy, services,
and Caddy deployment. The NAS must be on; its existing nightly host shutdown
and Wake-on-LAN configuration are unchanged.

The NAS image supplies native systemd services and a small controller, without
an additional container or an exposed VM-management API. `vms/inventory.json`
is the source for guest addresses, listening ports and idle policy. The command
`vm-on-demand enable` installs the selected socket units and a root-only runtime
configuration, disables domain autostart, and arms the idle timer. It never
creates or replaces a domain and does not reconcile other guests.

## Traffic and addresses

- `photos.vm` stays on K3s/Caddy, which forwards to `nas.vm:2283`, waking Immich.
- `music.vm` stays on K3s/Caddy, which forwards to `nas.vm:18096`, waking Jellyfin.
  NAS port 8096 remains reserved for the retained legacy service until migration.
- Connect Minecraft Java to `nas.vm:25565`, Bedrock to `nas.vm:19132` (also
  exposed on 19133). An optional `play.vm` DNS alias can point to the NAS.
- Keep `minecraft.vm`, `immich.vm`, and `jellyfin.vm` pointing at their guests.
  They are backend/NFS identities and direct maintenance addresses. Do not point
  those names to the NAS: the proxy would connect back to itself.

TCP sockets queue a connection during startup. The forwarding process starts
only when the guest port is listening. Bedrock uses a UDP relay with separate,
bounded client sessions and waits for a valid Bedrock status reply. UDP packets
may be lost while booting; the game client may need a second connection attempt.
Both IPv4 and IPv6 clients can use the NAS sockets; the Bedrock backend uses IPv4.
Discovery broadcasts/DLNA are not relayed. Clients must use the configured names
and ports. The backend sees the NAS's source address, so IP bans/access logs do
not distinguish individual clients; keep Minecraft account authentication and
whitelisting enabled.

A cold start may take minutes, particularly during first boot or image updates.
HTTP clients can time out and need a retry. Requests are not replayed after
forwarding begins. Server-list polls, health monitoring and phone background
requests can wake a VM; this implementation does not distinguish them from an
intentional visit. Avoid pointing continuous monitoring at the wake listeners
if you want the guests to sleep.

## Rollout on the NAS

Build/publish the updated NAS, VM base, Minecraft, Immich and Jellyfin role images
through the existing signed-image pipeline. Boot the new NAS image and update
the three guests so their `/usr/libexec/infrastructure/vm-idle-check` helper is
present. Complete each guest's first-boot rebase and application setup manually
before enabling demand activation. Keep K3s running normally.

Review the generated units locally before deployment:

```sh
python3 images/nas/bin/vm-on-demand render --output /tmp/vm-demand-units
```

On the NAS, from this repository root, provision missing guests using the
create-only `vm-deploy`. Then finish the legacy-service handover. Flush Minecraft
world saves using its role runbook, stop the old writers, and persistently mask
any installed legacy Minecraft/Bedrock units. For Jellyfin, stop and mask the NAS
service before starting its guest against the shared configuration:

```sh
sudo systemctl mask --now jellyfin.service
# When legacy Minecraft units exist, after flushing their worlds:
sudo systemctl mask --now minecraft.service bedrock.service
```

Activation refuses to start a guest while an installed legacy writer is active
or not persistently masked. A runtime-only mask is insufficient across reboots.
This command deliberately does not stop or mask applications for you. Verify
NFS exports, guest health, backups, signature trust and resources as described in
the individual role runbooks.

In **each of the Immich and Jellyfin guests**, create
`/etc/infrastructure/vm-idle-api-key`, owned by root with mode 0600, containing
only that application's API key. Immich needs an administrator-owned key with
`queue.read`; Jellyfin needs an API key authorized to read sessions and scheduled
tasks. Create them in each application's administration UI and install them
without putting the key in command-line arguments or shell history. These keys
stay inside the guest and only go to its loopback HTTP API. Missing keys keep
the VM running, while wake-on-access still works. Minecraft needs no new key.

Then enable the desired guests:

```sh
sudo vm-on-demand enable minecraft immich jellyfin
systemctl status vm-on-demand-idle.timer
systemctl list-sockets 'vm-demand-*'
```

Enable the NAS listeners **before** applying the Caddy route changes through
Flux. This changes the photo/music upstreams only; it does not change K3s's
lifecycle. Existing domains need this enable step even if inventory now says
`autostart: false`; `vm-deploy` remains create-only. Listener enablement survives
NAS reboots, and an update/rollback of the NAS image carries the controller.
After changes to inventory or generated units, disable the affected listener,
review/remove its old generated files under `/etc/systemd/system/vm-demand-*`
and `/etc/infrastructure/vm-on-demand/`, then enable it again. A plain enable
refuses to overwrite a differing installed policy.

## Idle decisions and maintenance

The NAS checks once a minute. Proxy connections, recent UDP traffic, application
work and backup/maintenance holds reset the full 30-minute interval. UDP session
expiry, connection keepalives and the check interval may extend the wait. The
controller reads a fresh local idle report over the existing QEMU guest-agent
channel; guest systemd timers run the probe every 30 seconds. The existing
SELinux permission for reading non-security files is used, without granting
the agent permission to execute application-management commands;
no SSH key or remotely accessible guest-control port is added.

The probe checks direct application connections and SSH sessions, OS upgrades,
and role backup markers. Minecraft checks Java and Bedrock player counts.
Jellyfin checks playing/paused sessions, transcoding and scheduled tasks. Immich
checks active, waiting, delayed and paused queue work, including scans, face
recognition, video conversion and database dumps. Failed or completed Immich
jobs alone do not hold the guest. A missing helper, blocked guest-agent file read,
API failure, stale/unknown report, clock skew, paused VM or failed shutdown keeps it running.
The controller never uses `virsh destroy`. An administrator who deliberately
stops only an application should hold the VM during that maintenance.

```sh
sudo vm-on-demand wake immich       # start now without opening a browser
sudo vm-on-demand hold immich       # keep running during maintenance/backups
sudo vm-on-demand release immich    # start a fresh 30-minute idle interval
sudo vm-on-demand sleep immich      # sleep now only if confirmed idle
sudo vm-on-demand disable immich    # disarm wake AND automatic shutdown
```

`disable` stops forwarding connections but leaves the guest running. Use it
before retiring a guest or returning to a legacy NAS application, then perform a
graceful VM shutdown and wait for `shut off` before unmasking the legacy service.
Update the Caddy route back to the legacy port before switching Jellyfin back.
Use `sleep` for routine on-demand shutdown, or disable activation before manual
`virsh` maintenance. Incoming traffic can wake a sleeping VM again.

For application-consistent snapshots, acquire a persistent NAS `hold` for every
participating on-demand VM **before** invoking any guest prepare hook. Release
it only after every finish hook succeeds. Leave it in place on recovery failure;
it survives host reboot and prevents shutdown of a half-finished backup. The
existing NAS snapshot service also inhibits idle shutdown while it is active.
These holds do not cancel the NAS's existing nightly physical power-off.

## Scheduled work

Guest schedules cannot run while their VM is off. Use NAS systemd timers to run
`/usr/bin/vm-on-demand wake immich` ahead of the scan/database-backup times chosen
in Immich. Put those schedules inside the NAS's powered-on hours and wake at
most 20 minutes beforehand; queued work then keeps the guest running. The NAS's
existing 21:30 shutdown means overnight schedules require changing the host
power schedule separately. The same consideration applies to Jellyfin scans
and guest OS updates. Until timers are configured, run scans/backups during an
awake session; socket traffic alone cannot guarantee daily maintenance.

## Validation

`just check-vm` includes controller and guest-response tests plus real loopback
TCP activation/readiness, UDP forwarding, and guest-agent file reads when those
system tools are available. Build the NAS image, generate the units with
`render`, then validate them with `systemd-analyze verify` inside that image.
On the live NAS, validate before relying on automatic shutdown:

1. Confirm the role-specific `vm-idle-report@NAME.timer` runs in each guest.
   Inspect `/run/vm-on-demand/idle.json`: it must report version 1, boolean
   `idle: true`, and a recent `checked_at` timestamp when idle. Confirm the NAS
   can read it via agent `guest-file-open/read/close`. Inspect AVCs if SELinux
   denies the read; do not disable SELinux. Missing permission fails closed.
2. With a guest shut off, connect through its NAS endpoint. Verify one VM start
   under simultaneous clients and successful photo upload/video playback,
   Jellyfin streaming, Java login, and Bedrock login after boot/retry.
3. Keep a player, stream, queued photo job, SSH session or backup hold active
   beyond 30 minutes and verify the VM stays running. Clear them and check it
   shuts down after a fresh quiet interval. Keep original media checksums.
4. Disable or disconnect the agent/API and verify it stays running. Test a wake
   while shutdown is finishing, failed startup/NFS, and a guest reboot/update.
5. Reboot the NAS, verify listeners re-arm without booting these guests, and
   confirm K3s still autostarts. Test a backup failure with hold/recovery/release.
   Check for any existing `libvirt-guests` resume-all policy on the live host;
   that service is disabled in the built NAS image, but local overrides may
   resume saved guests independently of their autostart flags.

Use `journalctl -u vm-on-demand-idle.service` and
`journalctl -u 'vm-demand-*'` on the NAS to diagnose startup and idle checks.
No live NAS behavior is claimed by the development-machine tests.
