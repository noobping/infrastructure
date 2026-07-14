# K3s cluster

This directory is the desired state for the single `k3s.vm` server. K3s runtime
state stays on the VM root disk. All 17 application claims are static NFS
volumes with hard mounts, FS-Cache, and a `Retain` policy.

Set the NAS address in `settings.yaml`; use its reserved IP if `nas.vm` is not
available during early boot. Traefik and local storage are disabled. ServiceLB
remains enabled for Caddy on ports 80 and 443.

## Secrets

Generate the age key once and keep an encrypted offline copy:

```sh
install -d -m 0700 ~/.config/sops/age
umask 077
age-keygen -o ~/.config/sops/age/keys.txt
age-keygen -y ~/.config/sops/age/keys.txt
```

Put the printed recipient in `cluster/.sops.yaml`, then copy and edit the three
examples. Use independent random values except for the Euro-Office JWT, which
must be identical in both Secret documents.

```sh
cd cluster
cp secrets/examples/nextcloud-secrets.sops.yaml.example secrets/nextcloud-secrets.sops.yaml
cp secrets/examples/paperless-secrets.sops.yaml.example secrets/paperless-secrets.sops.yaml
cp secrets/examples/euro-office-secrets.sops.yaml.example secrets/euro-office-secrets.sops.yaml

for file in secrets/*.sops.yaml; do
  sops --encrypt --in-place "$file"
done
```

Add the three encrypted filenames to `secrets/kustomization.yaml`, then verify
them and install the key used by Flux:

```sh
! rg -n 'REPLACE_BEFORE|REPLACE_WITH_THE_SAME' secrets --glob '*.sops.yaml'
for file in secrets/*.sops.yaml; do sops --decrypt "$file" >/dev/null; done

kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey="$HOME/.config/sops/age/keys.txt" \
  --dry-run=client -o yaml | kubectl apply -f -
cd ..
```

## Validate and deploy

From the repository root:

```sh
kubectl kustomize cluster >/tmp/infrastructure-cluster.yaml
kubectl apply --dry-run=client -f /tmp/infrastructure-cluster.yaml
! rg -n 'REPLACED_BY_KUSTOMIZE|REPLACE_BEFORE' /tmp/infrastructure-cluster.yaml

flux install
kubectl apply -k cluster/flux-system
flux reconcile source git infrastructure
flux reconcile kustomization infrastructure-cluster --with-source
```

## Cutover

Rehearse with copied exports. Never let a legacy service and its K3s
replacement write the same live NFS path.

1. Shut down K3s, verify the domain is off with no managed-save state, and
   temporarily disable autostart.
2. On the legacy NAS deployment, enable Nextcloud maintenance mode. Create the
   Nextcloud archive, PostgreSQL dumps, and Paperless `document_exporter`
   export while the old services still run.
3. Stop every legacy application Quadlet, then snapshot the backing Btrfs
   subvolumes. Never copy a live SQLite database or application directory.
4. Boot the current NAS deployment. Verify NFS is active and the legacy
   services replaced by K3s are absent before starting K3s and restoring its
   autostart. The retained NAS Jellyfin service remains enabled.
5. Reuse or restore the stopped NFS data, complete the checks below, then
   change service DNS and allow writes.

Preserve the Caddy CA under `/var/srv/ssd/caddy/data` and compare its root
certificate fingerprint before and after cutover.

Upgrade the old Nextcloud through supported major versions before using the
current image. Its stopped tree remains at `/var/lib/containers/nextcloud`;
convert SQLite into the empty PostgreSQL instance:

```sh
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c \
  'php occ db:convert-type --all-apps --password "$POSTGRES_PASSWORD" pgsql nextcloud nextcloud-postgresql nextcloud'

kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  su -s /bin/sh www-data -c 'php occ config:system:get dbtype'
```

The second command must return `pgsql`. Before leaving maintenance mode:

- remove restored wildcard/path overrides and use the domains, proxy CIDR, and
  external URL defined in `apps/nextcloud/workload.yaml`;
- run `occ db:add-missing-indices` and `occ maintenance:repair`;
- verify `www-data` can create and remove a file in `/var/srv/docs/shared`;
- run the Office connector and successfully edit and save a test document:

```sh
kubectl -n nextcloud create job --from=cronjob/nextcloud-office-configure \
  nextcloud-office-configure-manual
kubectl -n nextcloud logs -f job/nextcloud-office-configure-manual
```

For Paperless, restore its PostgreSQL dump into an empty database and keep its
database password and application secret unchanged. Confirm the NFS consume
directory is polled successfully. Also verify Uptime Kuma history and a
registry push and pull.

## Backups and rollback

Follow the [VM backup order](../vms/README.md#safety-and-backups). PostgreSQL
logical dumps are the restore source; live NFS database snapshots are only
crash-consistent. The backup contains a root-only but unencrypted Flux Secret,
so protect it and retain the separate encrypted age-key copy.

Before booting the legacy NAS deployment for rollback, stop K3s, Minecraft,
and any Jellyfin trial; clear managed-save state and disable K3s/Minecraft
autostart. Restore only into writable paths or writable snapshot clones. A Git
revert does not undo database schema changes.

## Checks

```sh
ssh nick@nas.vm sudo cat \
  /var/srv/ssd/caddy/data/caddy/pki/authorities/local/root.crt >root.crt
kubectl get nodes,pods,pvc,pv -A
flux get all --all-namespaces
curl --cacert root.crt https://nextcloud.vm/status.php
curl --cacert root.crt https://office.vm/healthcheck
curl --cacert root.crt https://registry.vm/v2/
```

All PVCs must be `Bound`. Verify service DNS, Paperless ingestion, Office
editing, Uptime Kuma history, `music.vm`, and registry push/pull.
