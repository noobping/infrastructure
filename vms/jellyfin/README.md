# Jellyfin VM

The NAS Jellyfin service remains authoritative. The guest is a manual trial
with domain autostart disabled. Its configuration, cache, music, and books are
NFS volumes; music and books are read-only. There is no data copy.

Stop the NAS service before starting the guest, and test the guest directly at
`jellyfin.vm` (`music.vm` still points to the NAS service):

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
starting the NAS service or rebooting the NAS, shut down the guest and remove
any managed-save state:

```sh
sudo virsh shutdown jellyfin
sudo virsh domstate jellyfin       # must report: shut off
sudo virsh dominfo jellyfin        # must report: Managed save: no
# If needed: sudo virsh managedsave-remove jellyfin
sudo systemctl start jellyfin.service
```

For a backup while the guest is active, follow the
[shared backup order](../README.md#safety-and-backups). Its prepare hook stops
Jellyfin; the finish hook restarts it if it was previously active.
