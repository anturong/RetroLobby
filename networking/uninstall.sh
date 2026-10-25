#!/bin/bash
# 卸载 EasyTier 组网
set -e

[ "$(id -u)" = "0" ] || { echo "请用 root 运行（先 sudo -i）"; exit 1; }

/userdata/system/services/easytier stop >/dev/null 2>&1 || true
batocera-services disable easytier >/dev/null 2>&1 || true

rm -f /userdata/system/services/easytier
rm -rf /userdata/system/easytier
rm -rf /userdata/system/easytier-gui
rm -f "/userdata/roms/ports/EasyTier GUI.sh"
rm -f /userdata/system/.local/share/applications/easytier-gui.desktop
rm -f /usr/share/applications/easytier-gui.desktop

echo "已卸载。retroarch.cfg 的联机配置保留，可用 /userdata/system/configs/retroarch/retroarch.cfg.bak-* 恢复。"
