# IPS

The image enables Suricata inline filtering and ClamAV on-access scanning.
ClamAV watches mutable data locations, updates signatures with `freshclam`,
and removes infected files directly instead of quarantining them.

ClamAV, Suricata, and gssproxy preparation runs as restricted, offline Ansible
policy containers. Each profile gets only its host account files, bundled
seeds, and service state mounts. Directory ownership and permissions converge
without replacing downloaded signatures or rules. Host tmpfiles creates
mount/scan roots; native service hooks restore SELinux labels and enable the
antivirus boolean. Rule downloads and daemon operation remain native.

The base embeds the policy runtime once, and Workstation/NAS inherit it.
Build `policy` before `ips`; the repository build commands and both CI graphs
enforce this order. To test all policy profiles, run `just test-policy` from
the repository root.

After building an IPS image, run `just test-ips-policy IMAGE` to extract its
embedded runtime and real seed files into a disposable tree. This runs each
service profile through its exact bind mounts, verifies repeated applies and
read-only checks, and checks that the merged Suricata rules reach the expected
top-level path. It does not start daemons or alter the running host.

Build the operating system:

```sh
podman build -t localhost/infrastructure-policy ../policy
podman build --build-arg POLICY_IMAGE=localhost/infrastructure-policy \
  -t ghcr.io/noobping/ips:latest .
```

Test the bootable container:

```sh
podman run --rm -it \
  --entrypoint /bin/bash \
  ghcr.io/noobping/ips:latest
```
