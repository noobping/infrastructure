
# Nick's NAS

## Identity

Create these host secret files before expecting the identity services to start:

```sh
/var/lib/containers/freeipa/secrets/admin-password
/var/lib/containers/freeipa/secrets/ds-password
/var/lib/containers/freeradius/secrets/ldap-bind-password
/var/lib/containers/freeradius/secrets/clients.conf
```

`clients.conf` should contain normal FreeRADIUS client definitions, for example:

```text
client ap01 {
    ipaddr = 192.168.1.20
    secret = replace-me
}
```

Router or local DNS must provide:

```text
A      ipa.nick.nas                 -> <nas-ip>
SRV    _ldap._tcp.nick.nas          -> 0 0 389 ipa.nick.nas.
SRV    _kerberos._tcp.nick.nas      -> 0 0 88 ipa.nick.nas.
SRV    _kerberos._udp.nick.nas      -> 0 0 88 ipa.nick.nas.
SRV    _kpasswd._tcp.nick.nas       -> 0 0 464 ipa.nick.nas.
SRV    _kpasswd._udp.nick.nas       -> 0 0 464 ipa.nick.nas.
```

FreeRADIUS only accepts users who are members of the FreeIPA group `radius-users`. The NAS bootstrap creates that group and a dedicated `radius-bind` LDAP bind account automatically after FreeIPA comes up for the first time.

## Updates

The GitLab pipeline is now a NAS-local alternative to GitHub Actions.

- GitHub and `ghcr.io/noobping/*` stay the default update path.
- GitLab CI builds into the NAS registry at `localhost:5000/noobping`.
- The NAS deploy job rebases the NAS itself from that local registry.
- Because this flow uses `localhost`, it is intended for builds and deploys on the NAS itself.

Create these directories and secret files on the NAS:

```text
/var/lib/containers/gitlab-runner/secrets/runner-token
/var/lib/containers/gitlab-runner/secrets/runner-description   # optional
/var/lib/containers/gitlab-runner/secrets/runner-tags          # optional
/var/lib/containers/gitlab-runner/secrets/cosign.key           # optional
/var/lib/containers/gitlab-runner/secrets/cosign.password      # optional
```

`runner-token` should contain either a modern GitLab runner authentication token (`glrt-...`) or a legacy registration token.

After the token exists, the NAS will auto-register its runner on boot. To trigger it immediately:

```sh
sudo systemctl restart gitlab-runner-register.service
sudo systemctl status gitlab-runner-register.service gitlab-runner.service
```

The runner is configured for the local GitLab CE and registry stack:

- GitLab UI/API: `http://nas:8929`
- Local registry: `http://localhost:5000`
- Runner tag: `nas-local` by default
- Build executor: privileged Docker executor backed by Podman

The GitLab pipeline builds `ips`, `workstation`, `nas`, and `desktop`, signs them when `cosign.key` is present, and exposes a manual `deploy:nas` job that rebases the NAS to `ostree-unverified-registry:localhost:5000/noobping/nas:$CI_COMMIT_SHA`.
