#!/bin/bash
# Batocera EasyTier 组网安装（核心 + 服务；GUI 存在时一并安装）
set -e

NET_NAME=${NET_NAME:-Batocera43.1}
NET_SECRET=${NET_SECRET:-RetroArch}

say() { echo "[install] $*"; }
die() { echo "[install] ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 运行（先 sudo -i）"
[ -d /userdata ] || die "找不到 /userdata，这不是 Batocera 系统"
[ "$(uname -m)" = "x86_64" ] || die "只支持 x86_64 的 Batocera"
HERE=$(cd "$(dirname "$0")" && pwd)
[ -x "$HERE/payload/easytier/easytier-core" ] || die "包不完整：缺少 payload/easytier/easytier-core"

say "安装 EasyTier 二进制到 /userdata/system/easytier"
install -d /userdata/system/easytier /userdata/system/logs
install -m 755 "$HERE/payload/easytier/easytier-core" /userdata/system/easytier/easytier-core
install -m 755 "$HERE/payload/easytier/easytier-cli" /userdata/system/easytier/easytier-cli
if [ -f "$HERE/VERSION" ]; then
  install -m 644 "$HERE/VERSION" /userdata/system/easytier/VERSION
fi

if [ -d "$HERE/payload/easytier-gui" ]; then
  if [ -d /userdata/system/easytier-gui ]; then
    BAK="/userdata/system/easytier-gui.bak-$(date +%Y%m%d-%H%M%S)"
    say "已有 GUI，备份到 $BAK"
    mv /userdata/system/easytier-gui "$BAK"
  fi
  say "安装 EasyTier GUI"
  cp -a "$HERE/payload/easytier-gui" /userdata/system/easytier-gui
  chmod +x /userdata/system/easytier-gui/start-gui.sh 2>/dev/null || true
  install -d /userdata/roms/ports /userdata/system/.local/share/applications /usr/share/applications
  if [ -f "$HERE/payload/files/EasyTier GUI.sh" ]; then
    cp "$HERE/payload/files/EasyTier GUI.sh" "/userdata/roms/ports/EasyTier GUI.sh"
    chmod +x "/userdata/roms/ports/EasyTier GUI.sh"
  fi
  if [ -f "$HERE/payload/files/easytier-gui.desktop" ]; then
    cp "$HERE/payload/files/easytier-gui.desktop" /userdata/system/.local/share/applications/
    cp "$HERE/payload/files/easytier-gui.desktop" /usr/share/applications/
  fi
fi

TAG="batocera-$(head -c 3 /dev/urandom | od -An -tx1 | tr -d ' \n')"
install -d /userdata/system/services
if [ -f /userdata/system/services/easytier ]; then
  cp /userdata/system/services/easytier \
     "/userdata/system/services/easytier.bak-$(date +%Y%m%d-%H%M%S)"
fi
render_service() {
  sed -e "s|@@IPMODE@@|$1|" \
      -e "s|@@HOSTNAME@@|$TAG|" \
      -e "s|@@NET_NAME@@|$NET_NAME|" \
      -e "s|@@NET_SECRET@@|$NET_SECRET|" \
      "$HERE/service-easytier.template" > /userdata/system/services/easytier
  chmod 755 /userdata/system/services/easytier
}
render_service "-d"
say "登记开机自启（batocera-services enable easytier）"
batocera-services enable easytier >/dev/null 2>&1 || say "警告：batocera-services enable 失败，请按 README 手动登记"

CFG=/userdata/system/configs/retroarch/retroarch.cfg
if [ -f "$CFG" ]; then
  say "备份并调整 RetroArch 联机配置"
  cp "$CFG" "$CFG.bak-$(date +%Y%m%d-%H%M%S)"
  set_kv() {
    if grep -q "^$1 = " "$CFG"; then
      sed -i "s|^$1 = .*|$1 = \"$2\"|" "$CFG"
    else
      echo "$1 = \"$2\"" >> "$CFG"
    fi
  }
  set_kv pause_nonactive false
  set_kv config_save_on_exit false
  set_kv netplay_nat_traversal false
  set_kv netplay_public_announce false
else
  say "警告：未找到 $CFG。先启动一次 RetroArch 再重新运行本脚本，或按 README 手动添加配置"
fi

say "启动 EasyTier 服务"
/userdata/system/services/easytier stop >/dev/null 2>&1 || true
sleep 1
/userdata/system/services/easytier start

wait_ip() {
  local i
  for i in $(seq 1 15); do
    ip -4 addr show tun0 2>/dev/null | grep -q "inet " && return 0
    sleep 1
  done
  return 1
}

if wait_ip; then
  say "DHCP 自动分配虚拟 IP 成功"
else
  say "DHCP 未在 15 秒内拿到 IP，改用随机静态 IP"
  FALLBACK="10.144.144.$(( (RANDOM % 190) + 40 ))"
  /userdata/system/services/easytier stop >/dev/null 2>&1 || true
  sleep 1
  render_service "-i $FALLBACK"
  /userdata/system/services/easytier start
  wait_ip || say "警告：仍未见 tun0 地址，查看 /userdata/system/logs/easytier.log"
fi

echo
echo "================ 安装完成 ================"
echo "网络: $NET_NAME"
echo "虚拟 IP: $(ip -4 addr show tun0 2>/dev/null | awk '/inet /{print $2; exit}')"
echo "节点名: $TAG"
echo
echo "对端状态:"
/userdata/system/easytier/easytier-cli peer 2>/dev/null | tail -6
echo
echo "大厅机地址由 /userdata/system/lobby-ui/lobby_ip 决定（默认 10.144.144.3）。"
echo "建议重启一次设备，让 RetroArch 配置完全生效。"
echo "=========================================="
