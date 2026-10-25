# EasyTier 组网包（RetroLobby）

把 Batocera 43.x（x86_64）接入 EasyTier 虚拟网络，供联机大厅和 RetroArch netplay 使用。
只装 `easytier-core` / `easytier-cli`；GUI 不包含在本包里。

- 网络名默认 `Batocera43.1`，密钥默认 `RetroArch`，可用环境变量覆盖：
  `NET_NAME=xxx NET_SECRET=yyy bash install.sh`
- 可用 `lobby-update` 自动更新：只有 EasyTier 版本变化时才会替换二进制，
  `/userdata/system/services/easytier`（本机 IP/节点名/网络名）保持不变，随后自动重启服务。

## 安装

```bash
tar -xzf easytier-netplay.tar.gz
cd easytier-netplay
bash install.sh
```

或从 Release 直接下载：

```bash
cd /userdata
curl -L -o easytier-netplay.tar.gz \
  https://github.com/anturong/RetroLobby/releases/latest/download/easytier-netplay.tar.gz
tar -xzf easytier-netplay.tar.gz && cd easytier-netplay && bash install.sh
```

## 验证

```bash
/userdata/system/easytier/easytier-cli peer
ip -4 addr show tun0
```

## 安全

- 网络名/密钥随包公开，任何拿到本包的人都能进入该虚拟网络；只发给信任的人。
- 部署前必须修改 Batocera 的默认 root 密码（出厂为 `linux`），否则同网段任何人都能拿到 root。

## 许可

EasyTier 以 LGPL-3.0 授权：<https://github.com/EasyTier/EasyTier>。
本包原样分发官方发布产物，未修改二进制。
