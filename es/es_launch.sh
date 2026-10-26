#!/bin/bash
# Fallback entry from the ES tile; lobby_watch.py usually opens the UI first.
# 如果 UI 已经在跑但被 EmulationStation 盖住，把已有窗口带到前台再退出，
# 否则按磁贴没有任何反应（ES 起来后会抢焦点，UI 留在后面）。
UI_PID=$(pgrep -f '/userdata/system/lobby-ui/lobby_ui\.py' | head -1)
if [ -n "$UI_PID" ]; then
    WID=$(DISPLAY=:0 xdotool search --pid "$UI_PID" 2>/dev/null | head -1)
    if [ -n "$WID" ]; then
        DISPLAY=:0 xdotool windowactivate --sync "$WID" 2>/dev/null
        DISPLAY=:0 xdotool windowraise "$WID" 2>/dev/null
    fi
    exit 0
fi
exec /usr/bin/python3 /userdata/system/lobby-ui/lobby_ui.py
