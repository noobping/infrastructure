# Jellyfin VM

The NAS Jellyfin service remains authoritative until the explicit handover.
The guest has domain autostart disabled and supports
[on-demand activation](../ON-DEMAND.md). Its configuration, cache, music, and books are
NFS volumes; music and books are read-only. There is no data copy.

Stop the NAS service before starting the guest, and test the guest directly at
`jellyfin.vm:8096`. After testing, mask the legacy NAS service and enable the
NAS wake listener before applying the Caddy change that routes `music.vm` through
`nas.vm:18096`:

```sh
sudo virsh autostart --disable jellyfin
sudo systemctl stop jellyfin.service
sudo virsh start jellyfin
```

After its first-boot rebase and reboot:

```sh
ssh nick@jellyfin.vm \
  'systemctl is-active cachefilesd.service && findmnt -t nfs,nfs4 -o SOURCE,TARGET,OPTIONS'
```

Never run both Jellyfin instances against the shared configuration. Before
returning to the legacy NAS service, shut down the guest and remove
any managed-save state:

```sh
sudo vm-on-demand disable jellyfin  # if activation was enabled
sudo virsh shutdown jellyfin
sudo virsh domstate jellyfin       # must report: shut off
sudo virsh dominfo jellyfin        # must report: Managed save: no
# If needed: sudo virsh managedsave-remove jellyfin
sudo systemctl unmask jellyfin.service
sudo systemctl start jellyfin.service
```

For a backup while the guest is active, follow the
[shared backup order](../README.md#safety-and-backups). Its prepare hook stops
Jellyfin; the finish hook restarts it if it was previously active.


## AudioMuse-AI

[AudioMuse](../audiomuse/README.md) runs in a separate on-demand VM and initially
connects to the retained NAS server. It does not authorize handover or start this
guest. The optional [plugin installer](install-audiomuse-plugin) pins ABI-compatible
0.1.55.0 for Jellyfin 10.11.11, checks the running version, and preserves existing
configuration. Its CA-bundle Quadlet drop-in enables trust of the administrator's
Caddy CA for authenticated `https://discovery.vm` calls. Follow the AudioMuse
runbook for setup, schedules and plugin updates before installing.
