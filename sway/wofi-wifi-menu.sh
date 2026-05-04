#!/usr/bin/env bash

# List available Wi-Fi networks
networks=$(nmcli -t -f SSID dev wifi | sort | uniq | awk 'NF' | wofi --show=dmenu --prompt="Select a Wi-Fi network")

# Exit if no network is chosen
[ -z "$networks" ] && exit 1

# Prompt for password
password=$(wofi --show=dmenu --lines=1 --password --prompt="Enter password for $networks:")

# Exit if no password is entered
[ -z "$password" ] && exit 1

# Attempt to connect
nmcli dev wifi connect "$networks" password "$password"
