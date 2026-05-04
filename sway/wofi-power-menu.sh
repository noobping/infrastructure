#!/usr/bin/env bash

# Display power menu options using wofi
choice=$(echo -e "Lock\nLogout\nReboot\nShutdown\nFirmware" | wofi --dmenu --prompt=Power --search Shutdown)

# Execute the chosen option
case "$choice" in
    Lock)
        swaylock
        ;;
    Logout)
        swaymsg exit
        ;;
    Reboot)
        systemctl reboot
        ;;
    Shutdown)
        systemctl poweroff
        ;;
    Firmware)
        systemctl reboot --firmware-setup
        ;;
    *)
        ;;
esac

