# VM base

The shared VM image adds the NFS client, `cachefilesd`, QEMU guest agent, TuneD
guest profile, and the required SELinux settings. FS-Cache is bounded so local
K3s and container runtime state retain space on the root disk.
