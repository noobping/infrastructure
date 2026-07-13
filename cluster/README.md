# Single-node K3s cluster

This directory is the desired state for the schedulable `k3s.vm` server. K3s
keeps pod and service addresses internal; only the VM and Caddy's K3s
ServiceLB are visible on the UniFi LAN. The NAS remains the NFS and backup
server.

Fedora CoreOS supplies the immutable container host, not a Kubernetes control
plane ([package manifest](https://github.com/coreos/fedora-coreos-config/blob/testing-devel/manifests/fedora-coreos.yaml)).
This role therefore uses the complete single-server K3s installation described
in the [K3s quick-start](https://docs.k3s.io/quick-start). Minikube is excluded:
its own [FAQ](https://minikube.sigs.k8s.io/docs/faq/) discourages persistent
production/network service use. Two or three server VMs on this same physical
NAS are still one failure domain, not HA; deploy three K3s servers only when
they can run on separate physical hosts.

## What is deployed

| Namespace | Workload | Persistent state |
|---|---|---|
| `ingress` | Caddy `2.11.4`, internal CA, K3s ServiceLB on TCP 80/443 and UDP 443 | `/data` and `/config` PVCs |
| `nextcloud` | Nextcloud `34.0.1-apache`, PostgreSQL `18.3`, Redis `8.8.0`, five-minute cron | local PVCs plus the shared-documents NFS claim |
| `office` | Euro-Office Document Server `v9.3.2` with a shared JWT | data, configuration, and log PVCs |
| `paperless` | Paperless-ngx `2.20.15`, PostgreSQL `18.3`, Redis `8.8.0`, Tika `3.3.1.0-full`, Gotenberg `8.32.0` | local state plus consume/media/export NFS claims |
| `monitoring` | Uptime Kuma `2.3.2` | local PVC |
| `registry` | CNCF Distribution Registry `3.1.1` | 100 GiB local PVC |

Every namespace starts with deny-all ingress and egress. Explicit policies
open only application flows, DNS, and the external access needed by the web
applications. Uptime Kuma deliberately has unrestricted egress because its job
is to monitor arbitrary LAN, VPN, and Internet targets. Caddy has port-limited
LAN egress to the independent Jellyfin VM.

Every image keeps its human-readable release tag and is also pinned to the verified
manifest-list digest. Have Renovate open reviewed tag-and-digest update PRs.

## Prerequisites

- One K3s server with `10.42.0.0/16` for pods and `10.43.0.0/16` for services.
  Install it with Traefik disabled; K3s ServiceLB must remain enabled.
- The K3s VM data disk mounted where K3s stores `/var/lib/rancher/k3s`.
- The bundled `local-path` StorageClass and an NFS client package in the VM
  image.
- Flux controllers, `sops`, `age`, and either `kubectl kustomize` or standalone
  `kustomize` on the administration machine.
- UniFi reservations and local DNS. `k3s.vm`, `apps.vm`, `nextcloud.vm`,
  `office.vm`, `paperless.vm`, `status.vm`, `registry.vm`, and `music.vm` all
  resolve to the K3s VM address. `jellyfin.vm` resolves directly to the
  Jellyfin VM.
- NFSv4 exports from the NAS for the paths in `storage/nfs-volumes.yaml`. Give
  the K3s VM read/write access to documents and Paperless paths. Keep media
  exported to the separate Jellyfin VM read-only.

Set `data.nfsServer` in `settings.yaml` to the reserved NAS IP if `nas.vm` is
not resolvable during early boot. The top-level Kustomize replacement writes
that value into every NFS PersistentVolume.

## SOPS and secrets

No usable placeholder Secret is part of the rendered cluster. Complete this
before starting Flux reconciliation:

```sh
cd cluster
age-keygen -o age.agekey
age-keygen -y age.agekey
```

Put the printed public recipient in `.sops.yaml`. Store `age.agekey` in the
password manager and never add it to Git. Create the Flux decryption secret:

```sh
kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey=./age.agekey \
  --dry-run=client -o yaml | kubectl apply -f -
```

Copy all three examples, generate a different random value for each requested
secret, and use the *same* 64-hex-character JWT in both Euro-Office Secret
documents:

```sh
cp secrets/examples/nextcloud-secrets.sops.yaml.example secrets/nextcloud-secrets.sops.yaml
cp secrets/examples/paperless-secrets.sops.yaml.example secrets/paperless-secrets.sops.yaml
cp secrets/examples/euro-office-secrets.sops.yaml.example secrets/euro-office-secrets.sops.yaml

openssl rand -base64 48
openssl rand -base64 48
openssl rand -base64 48
openssl rand -hex 32
```

Edit the copied files, then encrypt them in place:

```sh
sops --encrypt --in-place secrets/nextcloud-secrets.sops.yaml
sops --encrypt --in-place secrets/paperless-secrets.sops.yaml
sops --encrypt --in-place secrets/euro-office-secrets.sops.yaml
```

Add those three filenames under `resources:` in `secrets/kustomization.yaml`.
Before committing, both checks must succeed:

```sh
! rg -n 'REPLACE_BEFORE|REPLACE_WITH_THE_SAME' secrets --glob '*.sops.yaml'
sops --decrypt secrets/euro-office-secrets.sops.yaml >/dev/null
```

The SOPS private key is also backup-critical. Save an encrypted offline copy
and include the live `flux-system/sops-age` Secret in the application-consistent
backup export.

## Validate and bootstrap Flux

Render before pushing. `kubectl apply --dry-run=client` performs built-in type
checks; use kubeconform with the Flux CRD schemas as an additional CI check.

```sh
kubectl kustomize cluster > /tmp/infrastructure-cluster.yaml
kubectl apply --dry-run=client -f /tmp/infrastructure-cluster.yaml
rg -n 'REPLACED_BY_KUSTOMIZE|REPLACE_BEFORE' /tmp/infrastructure-cluster.yaml
```

The last command must print nothing. `nas.vm` should appear as every NFS
server unless `settings.yaml` was changed.

Install Flux once, commit and push this directory and the encrypted secrets,
then create the public read-only source and reconciliation object:

```sh
flux install
kubectl apply -k cluster/flux-system
flux reconcile source git infrastructure --with-source
flux get all --all-namespaces
```

`flux-system/sync.yaml` reads `main` from the public repository and reconciles
`./cluster`. It does not depend on the registry hosted inside this cluster.

## Rehearsal and migration

Perform this once with copies of all data before the maintenance window. The
source Nextcloud version must be upgraded one supported major version at a
time before placing its `/var/www/html` tree under the `34.0.1` image. Do not
ask the container entrypoint to skip unsupported major releases.

For each local-path PVC, use a short-lived helper pod mounting the claim and
copy a tar archive into it with `kubectl cp`. Preserve numeric owners, modes,
xattrs, and ACLs when creating the source archive. Never copy a live SQLite
database or application directory.

### Caddy CA

The current CA is inside `/var/srv/ssd/caddy/data`; the new Caddy PVC mounts at
the same `/data` path. Stop both Caddy instances, copy the entire contents into
the `ingress/caddy-data` PVC, and only then start the Kubernetes Deployment.
At minimum these files must survive:

```text
data/caddy/pki/authorities/local/root.crt
data/caddy/pki/authorities/local/root.key
```

After restoring, compare the old and new root certificate fingerprints:

```sh
openssl x509 -in /var/srv/ssd/caddy/data/caddy/pki/authorities/local/root.crt \
  -noout -sha256 -fingerprint
kubectl -n ingress exec deploy/caddy -- \
  cat /data/caddy/pki/authorities/local/root.crt | \
  openssl x509 -noout -sha256 -fingerprint
```

The two fingerprints are the acceptance test. Do not copy the old `/config`
directory unless there is a specific need: Caddy recreates runtime configuration
from the checked-in Caddyfile.

### Nextcloud SQLite to PostgreSQL

1. On the old instance, upgrade to a version from which Nextcloud 34 is a
   supported next step, run all pending app/database upgrades, enable
   maintenance mode, and take a consistent archive of `/var/www/html`.
2. Suspend Flux, stop the old Quadlet, restore that tree into the
   `nextcloud/nextcloud-data` PVC, and resume Flux. Wait for PostgreSQL and the
   Nextcloud pod. PostgreSQL must be empty except for its initial database.
3. Run the conversion in the new pod (the database password comes from its
   environment and is not printed):

```sh
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c \
  'php occ db:convert-type --all-apps --password "$POSTGRES_PASSWORD" pgsql nextcloud nextcloud-postgresql nextcloud'

kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c 'php occ config:system:get dbtype'
```

Before leaving maintenance mode, replace any restored legacy wildcard/path
settings explicitly:

```sh
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c \
  'set -eu
   php occ config:system:delete trusted_domains || true
   php occ config:system:set trusted_domains 0 --value=nextcloud.vm
   php occ config:system:set trusted_domains 1 --value=nextcloud.nextcloud.svc.cluster.local
   php occ config:system:delete trusted_proxies || true
   php occ config:system:set trusted_proxies 0 --value=10.42.0.0/16
   php occ config:system:set overwriteprotocol --value=https
   php occ config:system:set overwritehost --value=nextcloud.vm
   php occ config:system:set overwrite.cli.url --value=https://nextcloud.vm
   php occ config:system:delete overwritewebroot || true'
```

The second command must return `pgsql`. Then run `occ db:add-missing-indices`,
`occ maintenance:repair`, configure the external Local storage at
`/var/srv/docs/shared`, select Webcron/Cron in the admin UI, and disable
maintenance mode.
Before disabling maintenance mode, prove that the container's real Apache UID
can write the root-squashed shared export:

```sh
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c 'touch /var/srv/docs/shared/.acl-test && rm /var/srv/docs/shared/.acl-test'
```

Configure the Euro-Office connector from the suspended CronJob. This installs
the `eurooffice` app and sets the external browser URL, internal document
server URL, internal Nextcloud storage URL, JWT, and JWT header:

The Document Server workload uses the same `AuthorizationJWT` header and
explicitly permits private IP addresses so it can fetch documents from the
cluster-local Nextcloud `StorageUrl`. Metadata-address access remains disabled.
Before backups, the guest closes ingress and runs Document Server's shutdown
preparation while Nextcloud is still available for save callbacks. The drain
can take up to five minutes; a failed drain aborts the snapshot rather than
risk accepting an inconsistent Office edit.

```sh
kubectl -n nextcloud create job --from=cronjob/nextcloud-office-configure \
  nextcloud-office-configure-manual
kubectl -n nextcloud logs -f job/nextcloud-office-configure-manual
```

The final log line must report a successful document-server check. Open and
save a test document through `https://office.vm` before accepting writes.

### Paperless, Uptime Kuma, and registry
  `PAPERLESS_CONSUMER_POLLING=10` is set because NFS does not provide reliable
  inotify delivery; acceptance must include dropping a new file into `consume`
  from the NAS and confirming it is ingested without restarting the pod.

- Before stopping old Paperless, run `document_exporter` and create a custom
  format PostgreSQL dump. Restore `/var/lib/containers/paperless/data` into
  `paperless/paperless-data`, restore the database dump into
  `paperless-postgresql`, and keep the existing NFS media/export/consume
  directories. The new SOPS values must match the old database password and
  Paperless secret key when restoring an existing database.
- Restore `/var/lib/containers/uptime-kuma` into
  `monitoring/uptime-kuma-data`; verify the administrator, monitor list,
  status-page slug, and history before deleting the source.
- Restore `/var/lib/containers/registry` into `registry/registry-data`; test a
  pull and push through both `https://registry.vm/v2/` and the compatibility
  endpoint `https://apps.vm/v2/`.

Euro-Office has no old state in this migration. Keep its data/config/log PVCs
in backups after first use.

## Cutover

1. Rehearse all restores, then verify Caddy, Nextcloud, Euro-Office, Paperless,
   Uptime Kuma, and registry are Ready on temporary DNS names.
2. Enable Nextcloud maintenance mode, stop the old application Quadlets, dump
   PostgreSQL, stop Uptime/registry, snapshot source Btrfs subvolumes, and do
   the final copy.
3. Restore Caddy CA and local PVC data, convert Nextcloud, restore Paperless,
   and run the office connector job.
4. Point the service DNS records at the reserved `k3s.vm` address as one
   user-facing change. `nas.vm` must continue pointing at the physical host;
   `jellyfin.vm` and `minecraft.vm` continue pointing at their VMs.
5. Verify `https://nextcloud.vm/status.php`, document edit/save callbacks,
   Paperless ingestion and export, Uptime history, registry push/pull, and
   `https://music.vm` proxying to Jellyfin. Then disable maintenance mode.

Compatibility paths on `apps.vm` issue permanent redirects to the clean host
names. Only `/v2/` remains a reverse proxy because container clients rely on
that API path.

## Rollback and backups

Keep the old Quadlets and read-only source snapshots until acceptance is
complete. To roll back, suspend the Flux Kustomization, restore UniFi DNS to
the NAS address, stop Kubernetes writes, restore any post-cutover writes into
the source snapshots, and restart the old units. A Git revert plus
`flux reconcile kustomization infrastructure-cluster --with-source` rolls
back declarative cluster changes but does not roll back database schemas.

The weekly application-consistent backup must include PostgreSQL dumps,
Nextcloud data/config, Paperless local data plus its NFS directories, Caddy
`/data`, Uptime Kuma data, registry data, all Euro-Office PVCs, the K3s server
database/token, and an encrypted copy of the Flux age key. Quiesce or freeze
each workload before snapshot/send; a crash-consistent copy of a live database
is not an accepted backup.

## Acceptance checks

```sh
kubectl get nodes,pods,pvc,pv -A
flux get all --all-namespaces
curl --cacert root.crt https://nextcloud.vm/status.php
curl --cacert root.crt https://office.vm/healthcheck
curl --cacert root.crt https://registry.vm/v2/
```

Also verify that all eight service names resolve to the intended UniFi lease,
the Caddy Service has an external address, the NFS claims are Bound, no pod is
using `hostNetwork`, and no application Service other than Caddy is a
LoadBalancer or NodePort.
