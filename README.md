
![License](https://img.shields.io/badge/license-MIT-blue.svg)
[![Butane](https://github.com/noobping/infrastructure/actions/workflows/butane.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/butane.yml)
[![Workstation](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml/badge.svg)](https://github.com/noobping/infrastructure/actions/workflows/workstation.yml)

# Nick's Infrastructure

This project turns a Linux desktop into declarative infrastructure.

It provides a fully automated, immutable GNOME desktop built on Fedora CoreOS (FCOS).
The entire system, from OS installation to desktop environment and applications, is defined as code and built using Butane, bootable containers, and CI/CD pipelines.

There are no manual post-install steps. A fresh machine boots directly into a ready-to-use GNOME desktop. Favorite flathub applications can be installed using the pre-installed app store.
