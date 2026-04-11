
# Nick's NAS

## Identity

Create these host secret files before expecting the identity services to start:

```sh
/var/lib/containers/secrets/admin-password
/var/lib/containers/secrets/ds-password
/var/lib/containers/secrets/ldap-bind-password
/var/lib/containers/secrets/clients.conf
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
