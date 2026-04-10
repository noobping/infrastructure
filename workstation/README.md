
# Workstation

Build the operating systyem:

```sh
podman build -t ghcr.io/noobping/workstation:latest .
```

Test the bootable container:

```sh
podman run --rm -it \
  --entrypoint /bin/bash \
  ghcr.io/noobping/workstation
```

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
