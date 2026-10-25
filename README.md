# Batocera 异地联机大厅（形态 C · 自建 lobby + 可视化 UI）

2026-10-24 在两台 Batocera 43.1（EasyTier 虚拟网 `Batocera43.1`）上落地并验证：
`10.144.144.3` = n305（同时跑大厅服务器），`10.144.144.2` = 克隆二号机。

对局仍是 RetroArch 原生 netplay（TCP 55435），大厅只负责房间公告/浏览；
大厅挂了不影响直连。

> **安全必读：部署前必须修改 Batocera 的默认 root 密码。**
> Batocera 43.1 出厂 root 密码固定为 `linux` 且 SSH 默认开启。本项目用 root SSH 部署，
> EasyTier 虚拟网内任何设备、以及同局域网的任何机器，都能用这个公开的默认密码直接拿到 root，
> 进而改动系统、替换文件或操纵联机大厅。不改密码等于把两台机器和整个联机网络的控制权公开。

```bash
ssh root@<主机>
passwd                    # 设置强密码
```

改完后 `deploy.py` 用 `--password <新密码>`（或改用 SSH 密钥）部署，不要继续使用默认值。

## 交付内容

| 路径 | 作用 | 部署位置 |
|---|---|---|
| `src/lobby_ui.py` | pygame 全屏大厅 UI：建立主机 / 联机进入 两个菜单 | `/userdata/system/lobby-ui/lobby_ui.py` |
| `src/lobby_watch.py` | 屏幕守护：ES 一进入“联机大厅”游戏列表就自动拉起 UI（免去中间这级） | `/userdata/system/lobby-ui/lobby_watch.py` |
| `src/update.py` | `lobby-update`：从 GitHub 拉取最新版并重启 UI | `/userdata/system/lobby-ui/update.py` → `/usr/bin/lobby-update` |
| `VERSION` | 当前版本号（UI 页脚与更新比对） | `/userdata/system/lobby-ui/VERSION` |
| `src/boot-custom.sh` | 开机把 tmpfs 上会丢的 logo 复制回主题目录 | `/boot/boot-custom.sh`（FAT，需 remount rw） |
| `es/es_systems_lobby.cfg` | ES 自定义系统 `lobby`（首页磁贴入口） | `/userdata/system/configs/emulationstation/` |
| `es/es_launch.sh` | ES 磁贴命令：启动 lobby UI | `/userdata/system/lobby-ui/` |
| `es/gamelist.xml`、`es/lobby.png`、`es/lobby-cover.jpg` | 磁贴的游戏条目、系统 logo、封面 | `/userdata/roms/lobby/` 与主题 `art/logos/lobby.png` |
| `services/lobby_home` | 开机等 ES 起来后在顶层拉起 lobby UI | `/userdata/system/services/lobby_home` |
| `services/lobby_enter` | 常驻屏幕守护 `lobby_watch.py`（磁贴入口直达 UI） | `/userdata/system/services/lobby_enter` |
| `services/netplay_lobby` | 大厅服务器 + `/etc/hosts` 劫持 `lobby.libretro.com` | 大厅机 `/userdata/system/services/netplay_lobby` |
| `services/easytier.example` | EasyTier 服务模板（换 `NODE_IP/HOSTNAME`） | `/userdata/system/services/easytier` |
| `tools/make_logo.py` | 生成 "联机大厅" 透明 logo | 一次性 |
| `tools/uinput_keys.py` | 无手柄/远程注入按键（验证用） | 一次性 |
| `lobby-server/` | `netplay-lobby-server-go` 二进制 + `lobby.yaml` + 页面模板 + GeoIP | 大厅机 `/userdata/system/netplay-lobby/` |
| `deploy.py` | 一键部署到一台 Batocera（SSH/SFTP/paramiko） | Windows 侧 |

## 从零复现

需要两台同版本 Batocera 43.1（x86_64），root SSH 可登录。
**先按开头“安全必读”修改默认密码**（出厂为 `linux`），再用 `deploy.py --password` 部署。
`pygame`、`xdotool`、中文字体、`ffmpeg` 都是 Batocera 43.1 自带，无需安装；
Windows 侧只需要 Python 3 + paramiko。

### 1. 组网（每台都做）

本项目参考值：大厅机 n305 = `10.144.144.3`，对局机 = `10.144.144.2`。两种装法任选：

- 把同目录 `../batocera-easytier-netplay/batocera-easytier-netplay.tar.gz` 传到
  `/userdata`，解压后 `bash install.sh`（自带 `easytier-core` + GUI，DHCP 分配 IP）；
- 或自备 `easytier-core`（`easytier-linux-x86_64-v2.6.4.zip`），按 `services/easytier.example`
  建服务，把 `NODE_IP`、`HOSTNAME` 改成这台机器的值。

两台必须使用相同的 `--network-name Batocera43.1` 和 `--network-secret RetroArch`。
EasyTier 包 README 里的“房主地址 10.144.144.2”只针对它自带的 RetroArch 说明；
大厅部署以本 README 与 `deploy.py` 的参数为准（`--lobby-ip` 指向大厅机）。
验证：`ip -4 addr show tun0` 有 `10.144.144.x`，`easytier-cli peer` 能看到对端。

### 2. 部署（Windows 侧，在本目录执行）

```bash
pip install paramiko -i https://pypi.tuna.tsinghua.edu.cn/simple

# 大厅机：10.144.144.3，同时安装并启用大厅服务器
python deploy.py --host 192.168.232.129 --nick bato-n305 \
                 --node-ip 10.144.144.3 --lobby-ip 10.144.144.3 --lobby-server \
                 --update-repo <github-owner>/<repo>

# 对局机：10.144.144.2
python deploy.py --host 192.168.232.130 --nick bato-n305-2 \
                 --node-ip 10.144.144.2 --lobby-ip 10.144.144.3 \
                 --update-repo <github-owner>/<repo>
```

两台重启：`ssh root@<host> reboot`。

`deploy.py` 会写入：

- `/userdata/system/lobby-ui/`：`lobby_ui.py`、`lobby_watch.py`、`es_launch.sh`、`lobby.png`、`nick`、`lobby_ip`；
- `/userdata/system/configs/emulationstation/es_systems_lobby.cfg`（ES 磁贴）；
- `/userdata/roms/lobby/`：`.lobby` 占位、`gamelist.xml`、封面；
- `/userdata/system/services/lobby_home`、`lobby_enter`（+ 大厅机的 `netplay_lobby`、`/userdata/system/netplay-lobby/`）；
- `batocera.conf`：`global.netplay=1`、`global.netplay.nickname=<nick>`、`global.netplay.port=55435`；
- `/boot/boot-custom.sh`（开机恢复主题 logo；写入时自动 remount rw/ro）。

### 3. 复现自检

```bash
# 两台：开机后应直接看到大厅 UI；ESC 回 ES，首页有“联机大厅”磁贴
ps -eo args | grep -E 'lobby_ui|lobby_watch'
grep lobby.libretro /etc/hosts          # 10.144.144.3 lobby.libretro.com
cat /userdata/system/logs/boot_custom.log   # lobby logo restored
curl -s http://127.0.0.1/list           # [] 或房间 JSON
tail -5 /userdata/system/logs/lobby_watch.log  # watching for lobby gamelist

# 磁贴直达：ES 首页选中“联机大厅”→ A，约 1 秒后应直接是全屏大厅页
# （日志：score 0.9xx → match; opening lobby ui；ESC 后：lobby ui exited → sending ESC to ES）
LOBBY_WATCH_DEBUG=1 python3 /userdata/system/lobby-ui/lobby_watch.py  # 手动调试时打印每帧分数

# 一台建主后再看：应出现 <nick> / <game> / 10.144.144.x / connectable=true
```

机器相关的量只有：EasyTier 虚拟 IP、昵称（`--nick`）、大厅机 IP（`--lobby-ip`）。
主题按 Batocera 默认 `es-theme-carbon` 处理；换主题时改 `/boot/boot-custom.sh` 里的 `LOGO_DST`。

## UI 操作

- 入口：开机直接进本页；或 ES 首页选中“联机大厅”按 A，约 1 秒后直达本页（游戏列表一闪而过）。
- 主菜单：←/→ 选择“建立主机 / 联机进入”，Enter/A 确认，ESC 退回 ES 首页。
- 建立主机：系统 → 游戏（封面网格）→ 密码页（默认“无密码”，可直接 Enter 开始；
  也可直接打字或用方向键选屏幕键盘输入 1–16 位密码）→ `emulatorlauncher` 开房并公告。
- 游戏名与封面优先取 `gamelist.xml`（含刮削的中文名、`<image>`/`<thumbnail>`），
  没有刮削时回退到 ROM 文件名与 `images/<stem>-image.*`。
- 已开启标记：正在进行中的游戏卡片右上角显示绿色“已开启”；本机房间另有“本机”，
  有密码的房间显示“有密码”。本机退出游戏后，卡片显示“关闭中 Ns”倒计时
  （大厅 TTL 60 秒，无法立即删除）。
- 联机进入：在线房间卡片（connectable 圆点、玩家数、IP:端口、实时测速、密码/本机标记）→ 一键加入；
  有密码的房间启动 RetroArch 后会弹出密码输入框，由 RetroArch 自己的键盘界面输入。
- 房间列表 3 秒刷新；`R` 可手动刷新。

## 自动更新（GitHub）

发布仓库里放 `VERSION`、`src/`、`services/`、`es/`、`tools/` 即可；`lobby-update`
优先下载最新 Release 的 `lobby-ui.tar.gz`（由 `.github/workflows/release.yml` 在打 tag 时生成），
没有 Release 时回退到分支源码包（默认 `main`），并自动走 `ghfast.top` / `gh-proxy.com` 镜像。

```bash
lobby-update --check     # 只检查版本
lobby-update             # 安装最新版并重启大厅 UI
lobby-update --force     # 版本相同也重装
lobby-update --asset-url http://主机/lobby-ui.tar.gz   # 直接用指定包，无需配置仓库
```

仓库地址写在 `/userdata/system/lobby-ui/update_repo`（内容 `owner/repo`），
或部署时传 `--update-repo owner/repo`，也可临时 `lobby-update --repo owner/repo`。
给了 `--asset-url` 时不再要求 `update_repo`，可用于内网/本地包验证。
更新只覆盖 UI/服务/磁贴文件，保留 `nick`、`lobby_ip`、`update_repo` 与大厅服务器配置；
安装后直接重启 `lobby_watch.py` / `lobby_ui.py`（不走 `batocera-services`，它在部分机器上会卡住）。

## 关键实现点（踩过的坑）

### 1. 必须走 Batocera 的 `emulatorlauncher`

直接 `/usr/bin/retroarch` 会绕过 configgen：系统着色器（`global.shaderset=crt-scalefx`）、
bezel、分辨率覆盖全部失效。正确命令：

```bash
# 主机
emulatorlauncher -system fbneo -rom /userdata/roms/fbneo/1941.zip -core fbneo \
                 -netplaymode host -netplayport 55435
# 客户端
emulatorlauncher -system fbneo -rom /userdata/roms/fbneo/1941.zip -core fbneo \
                 -netplaymode client -netplayip 10.144.144.3 -netplayport 55435
```

`-core` 传核心短名（`fbneo`，不是 `.so` 路径），两端核心必须一致。

### 2. 昵称只能从配置注入

`emulatorlauncher` 没有 `-netplaynickname`。configgen 从 system config 读
`netplay.nickname`（`libretroGenerator.py` → `--nick`），所以把
`global.netplay.nickname=<nick>` 写进 `batocera.conf`（`global.*` 会合并进所有系统的配置）。
主机端口则读 `netplay.port`（不是 `netplay.server.port`），同法写 `global.netplay.port=55435`。

### 3. 房间取消没有“立即消失”

大厅协议只有 `/add`、`/list`；主机停止公告后房间靠 TTL 过期。
实测（`ttl_test.py`）：主机 SIGTERM 后 **约 56 秒**房间才消失（服务器 TTL 60s）。
“建立房间再取消”不会秒退，属服务器行为，不是 UI 的 bug。

### 3.1 房间密码走单游戏 appendconfig

Batocera 的 configgen 不支持 `netplay.password`，RetroArch 也没有启动参数可传密码，
但 configgen 会把 `/userdata/system/configs/retroarch/<system>/<rom 文件名>.cfg`
作为 `--appendconfig` 传给 RetroArch。开房前写入：

```ini
netplay_password = "..."
```

主机公告时 RetroArch 会自动带上 `has_password=1`（大厅 `/list` 可见，房间卡片显示“有密码”）。
主机连接期间必须保留该文件（RetroArch 在每个客户端握手时读取设置），游戏退出后立即删除，
避免影响下次从 ES 直接启动。Join 方的密码仍由 RetroArch 自带输入框处理。
清空密码时 UI 会删除这个文件里的 `netplay_password` 行与标记块。

### 3.2 已开启 / 关闭中标记

房间列表 3 秒刷新；用房间 `game_name`（ROM stem）与本地游戏做小写匹配。
本机判断用 `room.ip == tun0 IP`（大厅服务端用 `ctx.RealIP`），避免同名昵称误判。
`host_exit` 在 `emulatorlauncher` 返回后记录时间，60 秒内显示“关闭中 Ns”；
这是 UI 侧标记，不代表房间立即消失（服务器 TTL 行为未改）。

### 4. 开机 logo 的恢复必须早于 ES

根分区 `/usr` 在 tmpfs，主题里的 `lobby.png` 重启即丢。`/boot/boot-custom.sh` 由
`S00bootcustom` 在开机最早期执行，但此时 `/userdata` 还没挂载（S11share 才挂），
所以脚本在后台等待 `lobby.png` 出现后再复制，ES（S31）加载主题前完成。
日志：`/userdata/system/logs/boot_custom.log`。

### 5. 服务时序

`lobby_home` 由 `S99userservices` 在后台调用：轮询 `xdotool search --class emulationstation`
（最多 120s）+ 2s 后 `exec` UI。ES 磁贴入口走 `es_launch.sh`，两者互斥于同一时刻，
按 ESC 退出 UI 后服务进程也随之结束（下次开机再拉起）。

### 6. 磁贴直达：屏幕识别守护（lobby_watch.py）

ES 没有“进入系统”的钩子（只有 `startup-game`），所以 `lobby_enter` 常驻一个守护：
每秒抓游戏列表右侧预览框，与 `lobby-cover.jpg` 做 40x28 灰度 NCC。

- 阈值 0.80：列表页实测 0.93–0.98，ES 首页 0.00（同一封面在首页被放大铺底，NCC 对缩放不敏感）。
- 只抓预览框（`RECT` 比例 × xrandr 实际分辨率），整屏 `XGetImage` 在 vmwgfx 上会拖垮驱动。
- 匹配后先等 0.6s 再查 `lobby_ui.py` 是否已在运行（用户连按 A 时 ES 磁贴命令也会启动 UI），
  避免双开；UI 退出后**无条件**给 ES 发 Escape 回首页——没有合成器，UI 销毁后帧缓冲仍是
  旧画面，先截图再判断会误判成“已经离开列表”。Escape 后截图验证，仍在列表最多重试 3 次。
- 重新武装要求连续 2 帧低分，避免 UI 拆除瞬间的一帧旧画面触发“退出→重开”循环。
- `es_launch.sh` 也做了单实例检查（`pgrep -f lobby_ui\.py`），两条入口同时触发时只启动一个 UI。

换主题时改 `RECT`；分辨率变化不用管（比例 + xrandr）。

### 7. 焦点与按键

UI 启动/游戏退出后通过 `xdotool windowactivate --sync` 抢回焦点；
`emulatorlauncher` 启动较慢，抢 RetroArch 焦点预留 1.5s + 20s 轮询。
远程验证用的 uinput 脚本每次按键按住 60ms，避免 X 自动重复。

## 已验收（2026-10-24）

- 双机重启后自动进入大厅 UI；ESC 回 ES 首页；“联机大厅”磁贴带 logo。
- 磁贴直达：ES 首页按 A → 列表页约 1 秒后自动切到大厅页；ESC → 回 ES 首页，守护不重开；
  反复进出两次均正常（`lobby_watch.log`：`score 0.967 → match → lobby ui exited → sending ESC`）。
- 主机：UI 选 1941 → `/list` 出现 `bato-n305 / 1941 / 10.144.144.3:55435 / connectable=true`，
  RetroArch 带 `--set-shader .../denseDot-diffusion+ScaleFX.glslp`（系统着色器生效）。
- 联机：二号机 UI 选房间 → 以 `--connect 10.144.144.3` 启动 → 房间 `player_count=2`，画面同步。
- 大厅延迟 0.2–0.3ms（本机）；房间取消约 56s 后从列表消失。

## 已验收（2026-10-25 大厅增强）

两台 VM（10.144.144.3 / .2）实机验证：

- 游戏列表显示 `gamelist.xml` 中文名与封面（1941反击战、1944：燃烧的天空…），
  联机卡片的房间名也映射为中文。
- 密码页可直接打字或用屏幕键盘；留空开房 → `/list` 的 `has_password=false`，
  `1941.zip.cfg` 不生成；输入 1234 开房 → `/list` `has_password=true`，
  cfg 里出现 `netplay_password = "1234"`，退出游戏后 cfg 自动删除。
- 加入方卡片显示“有密码”，启动 RetroArch 后弹出 “Enter netplay server password”，
  输入后成功进入（`player_count=2`）。
- 另一台机器的游戏列表对进行中的房间显示绿色“已开启”；主机退出后本机显示
  “关闭中 50s”倒计时。
- `lobby-update --check` / `--force` 走本地 HTTP 包验证通过：下载、原子替换、
  保留 `nick`/`lobby_ip`、UI 与守护用新 PID 重启，页脚版本号正确。

## 已知限制

- 中途加入不会同步状态：客户端必须在主机开局前后进入（RetroArch replay 机制）。
- `player_count` 由主机公告刷新，加入后要等下一次公告（约 20s）才变。
- `lobby.libretro.com` 走 hosts 劫持，仅对使用系统解析器的进程生效（实测 RetroArch 公告可被劫持）。
- 大厅服务器仅 HTTP 80；没有删除/踢人接口。
- 磁贴入口不是真正的“跳过”：ES 会先画一帧游戏列表，约 1 秒后才切到大厅页；列表短暂可见属正常。
- 预览框坐标按 carbon 主题量取，换主题/分辨率过低时需要重新标定 `RECT`。
- 守护每秒一次局部截图，vmwgfx 上偶发 xtest/驱动报错（不影响使用），干净重启可恢复。
