
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

## Test Suricata

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
