#!/usr/bin/env bash
set -euo pipefail

install -d -m 0755 /var/lib/AccountsService/icons /var/lib/AccountsService/users
install -m 0644 /usr/share/pixmaps/faces/nick.png /var/lib/AccountsService/icons/nick
install -m 0644 /var/lib/AccountsService/default /var/lib/AccountsService/users/nick
