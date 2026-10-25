#!/bin/bash
# Fallback entry from the ES tile; lobby_watch.py usually opens the UI first.
pgrep -f '/userdata/system/lobby-ui/lobby_ui\.py' >/dev/null && exit 0
exec /usr/bin/python3 /userdata/system/lobby-ui/lobby_ui.py
