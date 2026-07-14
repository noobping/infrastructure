# Minecraft VM

Java and Bedrock use the existing NAS world directories through cached NFS
volumes. Flush and stop the legacy NAS services before starting the guest:

```sh
sudo podman exec systemd-minecraft rcon-cli save-all flush
sudo systemctl stop minecraft.service bedrock.service
sudo virsh start minecraft
```

Never run the legacy and guest writers together. Before booting a legacy NAS
deployment, shut down the guest, disable autostart, and remove any managed-save
state:

```sh
sudo virsh shutdown minecraft
sudo virsh autostart --disable minecraft
sudo virsh domstate minecraft      # must report: shut off
sudo virsh dominfo minecraft       # must report: Managed save: no
# If needed: sudo virsh managedsave-remove minecraft
```

Stop the legacy services before returning to the current deployment, then
restore autostart with `sudo virsh autostart minecraft`.

Guest consoles:

```sh
sudo mc-enter
sudo mc-send gamerule dofiretick false
```

For a consistent world backup, follow the
[shared backup order](../README.md#safety-and-backups). The hooks hold and
flush world saves before the snapshot, then resume them afterward.
