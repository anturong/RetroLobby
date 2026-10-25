#!/bin/bash
# Runs at S00, before /userdata is mounted, so wait for it in the background
# and then restore files that live on the tmpfs rootfs overlay.
LOGO_SRC=/userdata/system/lobby-ui/lobby.png
LOGO_DST=/usr/share/emulationstation/themes/es-theme-carbon/art/logos/lobby.png

(
    for _ in $(seq 1 600); do
        [ -f "$LOGO_SRC" ] && break
        sleep 0.1
    done
    [ -f "$LOGO_SRC" ] || exit 0
    mkdir -p "$(dirname "$LOGO_DST")"
    cp -f "$LOGO_SRC" "$LOGO_DST"
    if [ -f /userdata/system/lobby-ui/update.py ]; then
        chmod 755 /userdata/system/lobby-ui/update.py
        ln -sf /userdata/system/lobby-ui/update.py /usr/bin/lobby-update
    fi
    echo "$(date) lobby logo restored" >> /userdata/system/logs/boot_custom.log
) &

exit 0
