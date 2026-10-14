# GitLab Community Edition and trusted CI worker

GitLab and its worker are separate, CPU-only Fedora CoreOS VMs. GitLab has 8
vCPUs, 16 GiB RAM and a 160 GiB root disk; the worker has 4 vCPUs, 8 GiB RAM and
120 GiB. All live application and build state is on these SSD-backed guest disks.
Allow extra physical SSD capacity for image layers, GitLab's temporary backup,
and NAS backup bundles. The inventory does not reserve host RAM; check concurrent
VM demand before provisioning. Provisioning remains create-only.

GitLab CE 19.4.2 uses the official multi-architecture image pinned by OCI index
digest. Runner 19.4.1 and Cosign 2.6.4 downloads are checksum verified in the worker
image. Production guest definitions and the local pipeline target AMD64. The
bundled PostgreSQL, Redis, Gitaly, Sidekiq, registry and package registry stay
inside GitLab; their internal ports are not published. No Docker daemon, privileged
container, external database, Pages, search cluster, or object store is required.
The Omnibus container needs a writable root filesystem and root for its service
supervisor; capabilities are explicitly bounded and SELinux remains enabled.

## Deployment and first configuration

### UniFi DNS and one-command setup

The public service names can all point to the **NAS's reserved LAN IPv4 address**:

- `git.vm` — GitLab HTTPS on port 8443.
- `git-registry.vm` — container registry HTTPS on port 8443.
- `git-ssh.vm` — Git SSH on port 2222.

In UniFi Network, create three **Host (A)** DNS records with these names and the
same NAS address. In Network 9.4 the location is **Settings → Policy Table →
Create New Policy → DNS**; in 9.3 use **Settings → Policy Engine → DNS**.
Clients must use the UniFi gateway for DNS. Do not add WAN port forwarding.

Under **Client Devices → device Settings**, enable **Fixed IP Address** and
**Local DNS Record** for the backend VMs:

- MAC `52:54:00:00:00:36`: its own reserved IP, hostname `gitlab.vm`.
- MAC `52:54:00:00:00:37`: a different reserved IP, hostname `gitlab-runner.vm`.

Keep `nas.vm` pointing to the NAS and `k3s.vm` pointing to K3s. Do **not** point
these backend VM names at the NAS. No VM addresses are hard-coded in this repo.

TLS terminates **inside the GitLab VM**, using a small Caddy Quadlet on 8443.
The NAS only has a socket-activated TCP relay: **8443 → gitlab.vm:8443**. It forwards
the encrypted connection without inspecting HTTP or loading GitLab certificates. K3s can stay offline. Cockpit keeps `https://nas.vm/` on **443** and
its own certificate, administrator SSH keeps **22**, and the authoritative NAS
Jellyfin keeps **8096/8920**, its existing configuration and media. Git SSH uses
**2222**, separately from administrator SSH.

DNS does not select a port: use `https://git.vm:8443` in your browser and
`git-registry.vm:8443` for registry clients. The frontend has its own self-signed
CA on the VM at `/var/lib/gitlab/frontend/data`. It runs as UID 65532 with a
read-only root, no new privileges, only `NET_BIND_SERVICE` (required by the
upstream binary), a 256 MiB memory limit and half a CPU. Its host network is the
**guest VM's** network. Omnibus HTTP/registry ports 8080/5050 are bound only to VM
loopback. The health endpoint is loopback-only and never probes a sleeping VM.

The Runner's control API uses `https://gitlab.vm:8443` directly, including job
polling and result uploads. Its `clone_url` stays `https://git.vm:8443`, and registry
access uses the public registry name. This replaces HTTP path routing on the NAS:
there is no NAS TLS termination with which to inspect a polling URL. The existing
job/queue/Runner activity reports and post-drain recheck protect active CI work;
normal browser, Git, registry and pipeline-trigger requests use the wake relay.

Setup never stops, restarts, masks or reconfigures Cockpit, SSH or legacy Jellyfin,
and never starts the Jellyfin VM or performs a library handover. The nightly NAS
power schedule is preserved: services are unavailable while the NAS is powered off.
If another service owns 8443, listener activation fails without replacing it.

Self-signed certificates on separate services do not inherently conflict. GitLab's
CA must be trusted on each client, and the URL must match a certificate hostname.
Cockpit's certificate is neither replaced nor used for GitLab. Use the DNS names
above instead of an IP address; never work around errors by disabling TLS checks.

After building/deploying the updated NAS and both roles and completing their
first FCOS boot/rebase, verify the three SSH host fingerprints with your normal
`nick` SSH key (`nas.vm`, `gitlab.vm`, `gitlab-runner.vm`). Then, from this checkout:

```sh
just gitlab-setup --trust-local
```

This command is an explicit configuration action against those hosts; it is not
part of image builds or tests. `--trust-local` additionally installs the public
GitLab frontend CA on the Fedora computer running the command. Omit it on other systems
and import `dist/gitlab-setup/gitlab-root.crt` into their OS/browser trust store.
Other computers/phones need this public CA once too. No public CA, ACME account,
domain purchase, insecure registry setting, or certificate-verification bypass
is needed. The frontend uses `tls internal`, backed by its persistent self-signed
CA. Its private key stays in the GitLab VM; only the public CA is retrieved over SSH.

Setup asks once for the existing VM password. The Butane file stores a one-way
SHA-512 password hash, which GitLab cannot use as its password hash. Setup verifies
your input against the installed VM account and sets that same password on the
GitLab administrator. It also reuses the `nick` username and unrestricted SSH
public keys installed by Butane. Passwords travel through authenticated SSH and
standard input, never command-line arguments, repository files or setup logs.
Host-key checking stays enabled. The common NAS/VM sudo password must match;
different passwords require the manual setup below. The password must also meet
GitLab's password requirements; an incompatible password is not silently weakened.

The command holds/wakes the pair, drains the worker, installs CA trust in both
VMs and GitLab, configures the administrator, creates an **empty private**
`nick/infrastructure` project, selects the local CI file, protects the default
branch and tags, registers a locked protected project runner, generates its
separate signing identity and installs protected CI variables. It preserves an
existing signing identity and refuses a mismatched one. Rerunning it reuses the
project/worker/keys and synchronizes the GitLab password to the entered VM
password. It does not import/push repositories or change production image trust.

Open `https://git.vm:8443` and sign in as **nick** with your VM password. Import/push
the repository only when you are ready; an empty project has nothing to build.
Enable 2FA after setup. A failed setup retains the NAS hold and may leave the
worker stopped; rerun after correcting the error, then explicitly release any
pre-existing hold. Pre-existing maintenance holds are never removed automatically.

### Manual deployment and configuration

Build and publish the updated NAS, VM base, GitLab and Runner roles through the
existing hosted pipeline first. This avoids depending on GitLab to recover itself.
After approval, boot the new NAS image and provision from the repository root:

```sh
sudo vm-deploy gitlab gitlab-runner
```

Neither VM autostarts. Finish first boot and rebase using manual `virsh start`
before enabling demand activation. Supply DHCP reservations for MAC addresses
`52:54:00:00:00:36` and `52:54:00:00:00:37`; `gitlab.vm` and
`gitlab-runner.vm` must resolve to the guests. Point the three service names at
the NAS. The GitLab VM starts `gitlab-frontend.service` automatically. Enable the
NAS wake policy with `vm-on-demand enable gitlab`; the listeners are NAS 8443 →
guest 8443 (encrypted HTTPS for GitLab and registry) and NAS 2222 → guest 2222.
There is no GitLab web server, TLS termination, CA store or frontend opt-in marker
on the NAS.

If an earlier draft was already deployed, keep a maintenance hold, drain the
worker, stop only the old NAS `gitlab-frontend.service`, and disable its old
activation policy before switching. The controller refuses to overwrite a changed
policy: review/remove the old generated GitLab listener units and
`/etc/infrastructure/vm-on-demand/gitlab.json`, then enable the new policy. Preserve
or securely transfer the old frontend CA/data into the VM before first startup
if existing clients already trust it. Do not copy or replace Cockpit's certificate.
This transition is a manual deployment action; setup does not silently migrate it.
Guest port 22 remains administrator SSH. The NAS must already be powered on.

Install and trust the GitLab frontend's public root CA on your workstation and the worker
(`/etc/pki/ca-trust/source/anchors/infrastructure-gitlab.crt`, then
`update-ca-trust`). Read the public CA from
`/var/lib/gitlab/frontend/data/caddy/pki/authorities/local/root.crt` on the GitLab VM.
Do not copy its private CA key. Registry clients,
Git clients and the Runner must verify TLS; do not configure insecure registries.

GitLab bootstrap waits for readiness and disables account registration and public
project/group/snippet defaults before publishing its ready marker. The NAS waits
for that marker before forwarding user requests. Read the generated password in
`/var/lib/gitlab/config/bootstrap-password` through a root shell; log in as `root`,
change the password and enable 2FA. The generated bootstrap secret is persistent;
subsequent starts do not reset the account password. Use an SSH tunnel for first
setup if the Caddy route/listener is not active yet. Backend HTTP is a trusted-LAN
service; use Caddy for all ordinary access and do not expose guest ports to the
internet. Initial startup can take several minutes and clients may need to retry.

Bootstrap creates an administrator-owned `read_api` token for local activity
checks, persists it in the private GitLab configuration backup, and installs it
as `/etc/infrastructure/vm-idle-api-key`, root-owned mode 0600. It renews the
token during bootstrap when fewer than 30 days remain. It is used only on
loopback; missing/expired/non-admin tokens prevent automatic sleep. The
probe enumerates all project job pages and Sidekiq metrics; large instances may
exceed the bounded probe time and conservatively remain awake.

Optional SMTP settings belong in `/var/lib/gitlab/config/private.rb`, root-owned
0600. No email server is installed. SMTP, password-reset email and notifications
remain unavailable until a working relay is configured. Private overrides are
backed up; do not commit them. Restart GitLab after changing them.

## Worker registration and local CI

The setup command above automates this section. For manual configuration,
import/copy this infrastructure repository into the local GitLab when ready.
Existing remotes, repositories and hosted jobs are not migrated automatically.
In the project, create a **project runner** tagged `infrastructure-amd64`, locked
to this project, **protected**, with untagged jobs disabled. Protect the default
branch and release tags, and limit who can push/merge to them. Use the resulting
`glrt-` authentication token, not the obsolete registration-token workflow.

Register on the worker as root with `gitlab-runner register`, URL
`https://gitlab.vm:8443`, executor `shell`, and template
`/usr/share/gitlab-runner/config.toml`. Enter the token interactively. Keep the
result `/etc/gitlab-runner/config.toml` root-owned mode 0600. Registration templates
merge runner settings only: explicitly set the top-level `concurrent = 1`,
`check_interval = 10` and `listen_address = "127.0.0.1:9252"` from the template.
Retain its rootless environment, `clone_url = "https://git.vm:8443"` and build/cache paths.
Then start `gitlab-runner.service`. Its manager reads the secret as root and runs
jobs as UID 1011 without sudo; rootless Podman/Buildah use dedicated subordinate
IDs. The user service must remain running until jobs finish during shutdown.

Select `.gitlab/ci/self-hosted.yml` as this project's CI configuration path.
Only protected refs on `git.vm` run. This is a persistent shell executor for
trusted infrastructure code: jobs can access this worker account's caches and
other checkouts. Do not enable untrusted forks/contributions on it. No production
SSH credentials should be installed. The first workflow runs checks, builds the
graph sequentially, verifies/signs its AMD64 digests, publishes `:amd64` tags and
uploads installer files. It deliberately does not manufacture `:latest` multi-arch
tags. Hosted GitHub/GitLab pipelines retain both architectures.

Create a separate Cosign key pair outside the repository. Store the private key
as protected **file** variable `COSIGN_KEY`, its public key as protected file
variable `COSIGN_PUBLIC_KEY`, and the password as protected/masked `COSIGN_PASSWORD`.
The publish job uses key signatures without uploading private registry names to
public transparency services, verifies every signature, and rejects stale
non-default-branch publication. Keep an offline backup of this key pair and
password. GitLab's encrypted CI variables are covered by its database plus
`gitlab-secrets.json` backup. Never reuse production signing keys casually.

Locally produced installers reference `:amd64` and your internal registry.
Before using them, enroll the public CA and the local signing public key in the
target's container trust policy for that registry namespace, and arrange scoped
read-only registry credentials. This trust enrollment and switching production
update sources are manual deployment actions, not performed by this change.
Existing production image trust is untouched. Keep the hosted bootstrap images
available for recovery.

Set the project's registry cleanup policy to remove old run tags matching
`amd64-stable-run-.*`, keeping the newest ten for at least seven days. Preserve
`:amd64` and Cosign signature tags. Review package-registry installer retention
separately; those files consume the GitLab disk even after CI artifacts expire.
Do not run registry garbage collection during a push or a backup.

The worker refuses a build with less than 40 GiB free or surviving running
containers. To reclaim unused image layers, hold the pair on the NAS, drain the
worker with `systemctl stop gitlab-runner`, then run
`/usr/libexec/infrastructure/gitlab-runner-clean-cache`. Review and remove stale
checkout/cache directories separately. Restart the worker and release the hold.

## Wake, idle, and nightly shutdown

After both guests and monitoring credentials work, enable all GitLab listeners:

```sh
sudo vm-on-demand enable gitlab
sudo vm-on-demand wake gitlab
sudo vm-on-demand hold gitlab
sudo vm-on-demand release gitlab
```

Use `gitlab` as the lifecycle name for the whole pair. The worker has no separate
listener or independent idle policy. Web, Git SSH and registry traffic wake both.
Runner control API traffic, including `POST /api/v4/jobs/request`, goes directly
to the GitLab VM's TLS frontend, so polling neither wakes the pair nor touches the
NAS idle clock. Queued/running jobs and Runner activity still prevent sleep.
Do not add active Caddy checks or external monitoring against the wake URLs.

After 30 minutes without client traffic or active/queued CI work, the controller
waits for a safe background-work gap, shuts down the worker with SIGQUIT and waits
for it to finish. It keeps GitLab up for job completion/uploads, then waits for a
report whose probe started after the worker stopped. Normal clock synchronization
between NAS and guests is required. A newly queued job or incoming client restores
the worker. Housekeeping delays shutdown without resetting the full quiet period;
future scheduled/retry jobs remain persistent and do not keep the VM alive forever.
Unknown activity, stale guest reports, failed shutdown, backup markers and holds
prevent shutdown. There is no forced VM poweroff.

The NAS nightly service waits for both domains to be fully off, including when
listeners were disabled for maintenance. Existing AudioMuse and backup holds also
apply. Cancel any legacy scheduled `shutdown` reservation after updating the NAS
and restart `nightly-shutdown.service`, as in the AudioMuse runbook. An inactive
GitLab cannot fire its own scheduled pipelines; arrange a NAS wake timer during
powered-on hours for required schedules. This change does not power on the NAS.

## Backup and restore

Backups are explicit maintenance operations using the repository's existing
prepare/snapshot/finish procedure. They are **not automatically scheduled** by
this role. On the NAS, acquire `vm-on-demand hold gitlab` before either prepare
hook. Drain the worker (`systemctl stop gitlab-runner`); arrange a quiet maintenance
window with no Git/registry writes. Run `/usr/libexec/infrastructure/backup-prepare`
in each guest. GitLab creates its standard application archive; both roles export
private configuration and a checksum manifest. The worker's disposable caches and
checkouts are excluded. Verify success, then run the existing NAS Btrfs backup,
then both `backup-finish` hooks, restart the Runner, and release the NAS hold.

Completed bundles are `/var/lib/containers/gitlab/backups/backup.tar` and
`/var/lib/containers/gitlab-runner/backups/backup.tar` on the NAS, owned by dedicated
UIDs 1010 and 1011, mode 0600. Exports are root-squashed, hard-mounted, and checked
as NFS before writing. A failed dump/mount/transfer never replaces the last bundle
or clears the persistent backup marker. Investigate, retry, and explicitly finish
recovery before releasing a hold. Never back up a live qcow2 as an application
backup. Existing Btrfs retention keeps three weekly snapshots of the apps data.

Restore into fresh, isolated guests using the **exact backed-up GitLab CE version**:

1. Hold the pair and prevent client access. Set the role's
   `/var/lib/infrastructure/backup/ROLE/restoring` marker; stop the application.
   Extract each bundle into a root-only staging directory and run
   `sha256sum --check SHA256SUMS` there. Never extract unreviewed archives as root.
2. Restore GitLab's `config/` including bootstrap secret, `gitlab-secrets.json`,
   private settings and SSH keys into `/var/lib/gitlab/config`. Restore its
   `version` file. Restore the bundle's `frontend/` to `/var/lib/gitlab/frontend`
   with its numeric ownership (Caddy data UID 65532), keeping the frontend stopped
   during replacement. Put `application.tar` under `/var/lib/gitlab/data/backups`
   with a GitLab-compatible backup filename and ownership (`git`, UID 998 inside
   the container). Use the matching role image/configuration.
3. Clear the restoring marker only for controlled recovery. Start GitLab, stop
   Puma and Sidekiq using `podman exec gitlab gitlab-ctl stop SERVICE`, and run
   `podman exec -it gitlab gitlab-backup restore BACKUP=ID`. Restart GitLab and
   run `gitlab-rake gitlab:check SANITIZE=true`. Verify repositories, registry,
   packages, artifacts and encrypted CI variables before allowing clients.
4. Restore the worker's root-only config, signing directory and CA trust;
   rotate/re-register its token if required. Bootstrap reinstalls the backed-up
   monitoring token (or creates a replacement). Test a small CI
   job, finish recovery, and release the NAS hold.

GitLab's standard archive excludes Redis/Sidekiq queue contents and external
object storage. This deployment uses local registry/package storage. Drain CI and
inspect/reschedule pending background work after a restore. Preserve the Caddy CA
under `/var/lib/gitlab/frontend/data`: the GitLab role's backup bundle includes
this separate `frontend/` tree and its checksums. A missing CA makes backup fail,
retaining the previous export. A changed CA requires client trust enrollment.
No GitLab certificate state is stored in the NAS Caddy subvolume.

## Updates and troubleshooting

Change pinned versions/checksums through review. Use GitLab's required upgrade
stops, wait for background migrations, and make a fresh successful backup. Before
booting the new role, record `OLD_VERSION NEW_VERSION` in root-only
`/var/lib/gitlab/upgrade-approved`; the prepare guard requires a matching successful
backup. Upstream also checks its supported upgrade path. A successful bootstrap
records the new version and consumes authorization. An image rollback alone cannot
roll back a migrated database: restore matching data and configuration instead.

Inspect `gitlab.service`, `gitlab-runner.service`, `vm-idle-report@ROLE.service`,
NAS `vm-on-demand-idle.service`, and the local idle JSON for diagnosis. Missing
CA trust causes runner/registry TLS failures; never bypass verification to fix it.
A Runner without protected/tag matching jobs leaves them queued and keeps the pair
awake. Repeated housekeeper activity can delay shutdown; malformed API/metrics
responses fail closed. Review SELinux AVCs on Fedora CoreOS instead of disabling
enforcement. No deployment or production poweroff has been performed by repository
tests. See [test coverage](test/README.md).

Sources: [official container installation](https://docs.gitlab.com/install/docker/installation/),
[UniFi local DNS](https://help.ui.com/hc/en-us/articles/15179064940439-UniFi-DNS-Records-and-Local-Hostnames),
[Caddy local HTTPS](https://caddyserver.com/docs/automatic-https#local-https),
[GitLab password reset](https://docs.gitlab.com/security/reset_user_password/),
[Runner shell executor](https://docs.gitlab.com/runner/executors/shell/),
[backup contents](https://docs.gitlab.com/administration/backup_restore/backup_gitlab/),
[upgrade paths](https://docs.gitlab.com/update/upgrade_paths/).
