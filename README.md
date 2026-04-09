
![License](https://img.shields.io/badge/license-MIT-blue.svg)
[![Butane](https://github.com/noobping/infrastructure/actions/workflows/butane.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/butane.yml)
[![IPS](https://github.com/noobping/infrastructure/actions/workflows/ips.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/ips.yml)
[![Workstation](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml)
[![NAS](https://github.com/noobping/infrastructure/actions/workflows/nas.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/nas.yml)

# Nick's Infrastructure

Declarative infrastructure for workstations and servers.

This project delivers fully automated, immutable system images built on Fedora CoreOS (FCOS).  
From GNOME-based workstations to headless servers and storage nodes, the entire stack is defined as code using Butane, bootable containers, and CI/CD pipelines.

Nodes automatically configure themselves at first boot and continuously maintain their desired state.

## Test IPS

Confirm Suricata is running and its rules are present:

```sh
sudo systemctl status suricata.service suricata-prepare.service
sudo journalctl -u suricata.service -b --no-pager | tail -n 50
sudo systemctl status suricata-update.timer
sudo test -s /var/lib/suricata/rules/suricata.rules && echo rules-ok
```

Confirm the workstation firewall is queueing host traffic to NFQUEUE:

```sh
sudo firewall-cmd --permanent --direct --get-all-rules | grep SURICATA
sudo nft list ruleset | grep -E 'SURICATA_HOST|queue num 0'
```

Test detection with a temporary rule:

```sh
sudo cp /var/lib/suricata/rules/suricata.rules /var/lib/suricata/rules/suricata.rules.bak
echo 'alert icmp any any -> any any (msg:"WORKSTATION SURICATA TEST"; sid:9900001; rev:1;)' | sudo tee -a /var/lib/suricata/rules/suricata.rules
sudo systemctl restart suricata
ping -c1 1.1.1.1
sudo tail -n 20 /var/log/suricata/fast.log
```

Test inline blocking by changing `alert` to `drop`:

```sh
echo 'drop icmp any any -> any any (msg:"WORKSTATION SURICATA DROP TEST"; sid:9900002; rev:1;)' | sudo tee -a /var/lib/suricata/rules/suricata.rules
sudo systemctl restart suricata
ping -c1 1.1.1.1
```

Restore the original rules after testing:

```sh
sudo mv /var/lib/suricata/rules/suricata.rules.bak /var/lib/suricata/rules/suricata.rules
sudo systemctl restart suricata
```

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
