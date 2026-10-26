#!/usr/bin/env python3
import datetime, fcntl, json, math, os, re, signal, socket, subprocess, threading, time, urllib.request
import xml.etree.ElementTree as ET
import pygame

LOBBY_LIST = os.environ.get("LOBBY_URL", "http://lobby.libretro.com/list")
LOBBY_HOST = "lobby.libretro.com"
LOBBY_PORT = 80
REFRESH_SEC = 3.0
NETPLAY_PORT = 55435
ROOM_TTL = 60.0
RETROARCH_CFG_DIR = "/userdata/system/configs/retroarch"
VERSION_FILE = "/userdata/system/lobby-ui/VERSION"
PASSWORD_MAX = 16
PW_MARK_BEGIN = "# lobby-ui netplay password begin"
PW_MARK_END = "# lobby-ui netplay password end"
LAUNCH_LOCK = "/tmp/lobby-ui-launch.lock"
INSTANCE_LOCK = "/tmp/lobby-ui-instance.lock"
EASYTIER_CLI = "/userdata/system/easytier/easytier-cli"

FONT_CJK = "/usr/share/dosbox-x/SarasaGothicFixed.ttf"
FONT_FALLBACK = "/usr/share/fonts/dejavu/DejaVuSans.ttf"
FONT_PATH = FONT_CJK if os.path.isfile(FONT_CJK) else FONT_FALLBACK

BG_TOP = (10, 14, 20); BG_BOT = (20, 29, 40)
CARD = (23, 32, 43); CARD_EDGE = (44, 60, 78)
TEXT = (236, 239, 241); MUTED = (140, 160, 176); ACCENT = (79, 195, 247)
GREEN = (102, 187, 106); RED = (239, 83, 80); AMBER = (255, 183, 77)
HOST_C = (102, 187, 106); JOIN_C = (79, 195, 247)

ES_SYSTEMS = "/usr/share/emulationstation/es_systems.cfg"
NETPLAY_SYSTEMS = ["fbneo", "mame", "nes", "snes", "megadrive", "gba"]
SYSTEM_LABEL = {"fbneo": "街机 · FBNeo", "mame": "街机 · MAME", "nes": "FC / NES",
                "snes": "SFC / SNES", "megadrive": "MD / Genesis", "gba": "GBA"}

state = {"rooms": [], "error": "", "updated": 0.0, "rtt": {}, "peers": {}, "lobby_ms": None,
         "systems": [], "systems_ready": False, "notice": None, "host_exit": None}
lock = threading.Lock()
refresh_evt = threading.Event()
stop_evt = threading.Event()
cover_cache = {}
cover_path_cache = {}
local_ip_cache = {"ip": ""}


def read_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or "dev"
    except OSError:
        return "dev"


VERSION = read_version()
ENV = dict(os.environ)
ENV["DISPLAY"] = ":0"
ENV["HOME"] = "/userdata/system"
ENV["XDG_CONFIG_HOME"] = "/userdata/system/configs"


def http_get(url, timeout=3.0):
    req = urllib.request.Request(url, headers={"User-Agent": "lobby-ui"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def measure_tcp(ip, port, tries=3):
    if not ip or not port:
        return None
    best = None
    for _ in range(tries):
        t0 = time.perf_counter()
        try:
            s = socket.create_connection((ip, int(port)), timeout=0.8)
            s.close()
        except Exception:
            return None
        ms = (time.perf_counter() - t0) * 1000.0
        best = ms if best is None else min(best, ms)
        time.sleep(0.03)
    return best


def fetch_peers():
    """easytier-cli peer -> {ip: {"cost": "p2p"/"relay(N)"/"local", "lat": ms}}"""
    peers = {}
    out = None
    for cmd in (EASYTIER_CLI, "easytier-cli"):
        try:
            out = subprocess.check_output([cmd, "peer"], stderr=subprocess.DEVNULL,
                                          timeout=3)
            break
        except FileNotFoundError:
            continue
        except Exception:
            return peers
    if out is None:
        return peers
    out = out.decode("utf-8", "replace")
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        ip = parts[1].split("/")[0].strip()
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
            continue
        try:
            lat = float(parts[4])
        except ValueError:
            lat = None
        peers[ip] = {"cost": parts[3].lower(), "lat": lat}
    return peers


def fetch_rooms():
    while not stop_evt.is_set():
        rooms, err = [], ""
        try:
            data = json.loads(http_get(LOBBY_LIST))
            rooms = [item.get("fields", item) for item in data]
        except Exception as exc:
            err = str(exc)
        rooms.sort(key=lambda f: str(f.get("created", "")), reverse=True)
        rtt = {f.get("id"): measure_tcp(f.get("ip"), f.get("port")) for f in rooms}
        peers = fetch_peers()
        lobby_ms = measure_tcp(LOBBY_HOST, LOBBY_PORT, tries=2)
        with lock:
            state.update(rooms=rooms, error=err, rtt=rtt, peers=peers, lobby_ms=lobby_ms,
                         updated=time.time())
        refresh_evt.wait(REFRESH_SEC)
        refresh_evt.clear()


def local_ip():
    if local_ip_cache["ip"]:
        return local_ip_cache["ip"]
    ip = ""
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "tun0"],
                                       stderr=subprocess.DEVNULL).decode()
        ip = out.split("inet ")[1].split("/")[0]
    except Exception:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.144.144.3", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = ""
    local_ip_cache["ip"] = ip
    return ip


def nick():
    try:
        with open("/userdata/system/lobby-ui/nick") as fh:
            value = fh.read().strip()
            if value:
                return value
    except OSError:
        pass
    ip = local_ip()
    if ip:
        last = ip.rsplit(".", 1)[-1]
        return "bato-n305" if last == "3" else "bato-n305-" + last
    return "bato-" + socket.gethostname().lower()


def _gamelist_image(romdir, value):
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("./"):
        value = value[2:]
    if not os.path.isabs(value):
        value = os.path.join(romdir, value)
    return value if os.path.isfile(value) else None


def load_gamelist(romdir):
    """stem(lower) -> {display, image}; Batocera 抓取的中文名与封面都在这里。"""
    meta = {}
    try:
        root = ET.parse(os.path.join(romdir, "gamelist.xml")).getroot()
    except Exception:
        return meta
    for node in root.findall("game"):
        raw = (node.findtext("path") or "").strip()
        if not raw:
            continue
        rel = raw[2:] if raw.startswith("./") else raw
        stem = os.path.splitext(os.path.basename(rel))[0].lower()
        image = (_gamelist_image(romdir, node.findtext("image"))
                 or _gamelist_image(romdir, node.findtext("thumbnail"))
                 or _gamelist_image(romdir, node.findtext("marquee")))
        meta[stem] = {"display": (node.findtext("name") or "").strip(), "image": image}
    return meta


def find_cover_path(romdir, stem, display=""):
    key = (romdir, stem, display)
    if key in cover_path_cache:
        return cover_path_cache[key] or None
    images = os.path.join(romdir, "images")
    names = [stem] + ([display] if display and display != stem else [])
    found = ""
    for base in names:
        for folder in (images, os.path.join(romdir, "downloaded_images")):
            for suffix in ("-thumb.png", "-thumb.jpg", "-thumb.jpeg", "-image.png",
                           "-image.jpg", "-image.jpeg", "-marquee.png", "-marquee.jpg",
                           ".png", ".jpg", ".jpeg"):
                p = os.path.join(folder, base + suffix)
                if os.path.isfile(p):
                    found = p
                    break
            if found:
                break
        if found:
            break
    cover_path_cache[key] = found
    return found or None


def parse_systems():
    try:
        root = ET.parse(ES_SYSTEMS).getroot()
    except Exception:
        return []
    cfgs = {}
    for sysnode in root:
        name = sysnode.findtext("name")
        if name not in NETPLAY_SYSTEMS:
            continue
        exts = (sysnode.findtext("extension") or "").split()
        cores = [c.text for c in sysnode.findall(".//core") if c.text]
        cfgs[name] = {"ext": exts, "cores": cores,
                      "fullname": sysnode.findtext("fullname") or name}
    systems = []
    for name in NETPLAY_SYSTEMS:
        cfg = cfgs.get(name)
        if not cfg:
            continue
        core_so = ""
        for core in cfg["cores"]:
            cand = "/usr/lib/libretro/%s_libretro.so" % core
            if os.path.isfile(cand):
                core_so = cand
                break
        if not core_so:
            continue
        romdir = "/userdata/roms/" + name
        try:
            files = sorted(os.listdir(romdir), key=str.lower)
        except OSError:
            continue
        meta = load_gamelist(romdir)
        games = []
        for fn in files:
            p = os.path.join(romdir, fn)
            if fn.startswith(".") or not os.path.isfile(p):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if cfg["ext"] and ext not in cfg["ext"]:
                continue
            stem = os.path.splitext(fn)[0]
            info = meta.get(stem.lower(), {})
            display = info.get("display") or stem
            cover = info.get("image") or find_cover_path(romdir, stem, display)
            games.append({"name": stem, "display": display, "path": p, "cover": cover})
        if games:
            systems.append({"name": name, "label": SYSTEM_LABEL.get(name, cfg["fullname"]),
                            "core": core_so, "games": games})
    return systems


def scanner():
    systems = parse_systems()
    with lock:
        state.update(systems=systems, systems_ready=True)


def load_cover(path, box):
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime, box)
    if key in cover_cache:
        return cover_cache[key]
    try:
        img = pygame.image.load(path)
        img = img.convert_alpha() if img.get_alpha() else img.convert()
        w, h = img.get_size()
        scale = min(box[0] / w, box[1] / h, 1.0)
        if scale < 1.0:
            img = pygame.transform.smoothscale(img, (max(1, int(w * scale)), max(1, int(h * scale))))
        cover_cache[key] = img
        return img
    except Exception:
        return None


def fit_font(font_path, text, size, max_w):
    while size > 12:
        font = pygame.font.Font(font_path, size)
        if font.size(text)[0] <= max_w:
            return font
        size -= 2
    return pygame.font.Font(font_path, 12)


def truncate(font, text, max_w):
    if font.size(text)[0] <= max_w:
        return text
    ell = "…"
    while text and font.size(text + ell)[0] > max_w:
        text = text[:-1]
    return text + ell


def set_notice(text, secs=3.5):
    with lock:
        state["notice"] = {"text": text, "until": time.time() + secs}


def _active_window_ids():
    try:
        out = subprocess.run(["xdotool", "getactivewindow"],
                             capture_output=True, env=ENV, timeout=2)
        return out.stdout.split()
    except Exception:
        return []


def focus_self(delay=0.0):
    def run():
        if delay:
            time.sleep(delay)
        wid = None
        for _ in range(40):
            try:
                out = subprocess.run(["xdotool", "search", "--pid", str(os.getpid())],
                                     capture_output=True, env=ENV, timeout=2)
                ids = out.stdout.split()
                if ids:
                    wid = ids[0]
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not wid:
            return
        # EmulationStation 可能在 UI 之后才启动并把焦点抢回去，所以首次激活后
        # 在 +1.5s / +4.5s / +9.5s 复查；只有自己不在前台时才重新激活，
        # 已经在前台就什么都不做，避免和用户抢窗口。
        for wait in (0.0, 1.5, 3.0, 5.0):
            if wait:
                time.sleep(wait)
            if _active_window_ids()[:1] == [wid]:
                continue
            try:
                subprocess.run(["xdotool", "windowactivate", "--sync", wid.decode()],
                               env=ENV, timeout=3)
                subprocess.run(["xdotool", "windowraise", wid.decode()],
                               env=ENV, timeout=3)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def activate_window(cls, delay=0.0):
    def run():
        if delay:
            time.sleep(delay)
        for _ in range(80):
            try:
                out = subprocess.run(["xdotool", "search", "--class", cls],
                                     capture_output=True, env=ENV, timeout=2)
                ids = out.stdout.split()
                if ids:
                    subprocess.run(["xdotool", "windowactivate", "--sync", ids[-1].decode()],
                                   env=ENV, timeout=3)
                    return
            except Exception:
                pass
            time.sleep(0.25)
    threading.Thread(target=run, daemon=True).start()


def core_short(system):
    base = os.path.basename(system["core"])
    if base.endswith("_libretro.so"):
        base = base[:-len("_libretro.so")]
    return base


def _pids_matching(pred):
    pids = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % name, "rb") as fh:
                args = [a for a in fh.read().split(b"\0") if a]
        except OSError:
            continue
        if pred(args):
            pids.append(int(name))
    return pids


def _ppid(pid):
    try:
        with open("/proc/%d/status" % pid, encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return -1


def netplay_emulator_pids():
    """大厅启动的联机会话。UI 运行期间它必然是残留：启动游戏时 UI 是被阻塞的。"""
    launchers = _pids_matching(
        lambda args: b"/usr/bin/emulatorlauncher" in args and b"-netplaymode" in args)
    pids = set(launchers)
    if launchers:
        for pid in _pids_matching(lambda args: any(a.endswith(b"/retroarch") for a in args)):
            if _ppid(pid) in launchers:
                pids.add(pid)
    # launcher 已退出、只剩联机 RetroArch 的孤儿
    for pid in _pids_matching(
            lambda args: any(a == b"--host" or a.startswith(b"--connect") for a in args)):
        pids.add(pid)
    return sorted(pids)


def clear_leftover_emulators():
    pids = netplay_emulator_pids()
    if not pids:
        return 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 3.0
    while time.time() < deadline and netplay_emulator_pids():
        time.sleep(0.1)
    for pid in netplay_emulator_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    set_notice("已结束 %d 个残留联机进程" % len(pids), 4)
    return len(pids)


def drop_queued_input():
    # 启动/退出游戏瞬间积压的按键不能再次触发启动
    try:
        pygame.event.clear([pygame.KEYDOWN, pygame.KEYUP,
                            pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])
    except Exception:
        pass


def launch_game(system, game, netplay_args):
    """启动联机游戏；跨进程加锁，并发调用只有一个能真正启动。"""
    fd = os.open(LAUNCH_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            set_notice("已有游戏正在启动或运行中", 4)
            return False
        drop_queued_input()
        clear_leftover_emulators()
        # 走 Batocera 正常启动管线，系统配置（着色器/bezel/分辨率）才会生效
        activate_window("retroarch", 1.5)
        subprocess.run(["/usr/bin/emulatorlauncher", "-system", system["name"], "-rom", game["path"],
                        "-core", core_short(system)] + netplay_args, env=ENV)
        focus_self(0.3)
        drop_queued_input()
        return True
    finally:
        os.close(fd)


def pergame_cfg_path(system, game):
    return os.path.join(RETROARCH_CFG_DIR, system["name"],
                        os.path.basename(game["path"]) + ".cfg")


def write_netplay_password(system, game, password):
    """写入/清除单游戏 appendconfig；主机密码只在本局期间存在。"""
    path = pergame_cfg_path(system, game)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    out, skipping = [], False
    for ln in lines:
        if ln.strip() == PW_MARK_BEGIN:
            skipping = True
            continue
        if skipping:
            if ln.strip() == PW_MARK_END:
                skipping = False
            continue
        if re.match(r"^\s*netplay_password\s*=", ln):
            continue
        out.append(ln)
    if password:
        escaped = password.replace("\\", "\\\\").replace('"', '\\"')
        out.extend([PW_MARK_BEGIN, 'netplay_password = "%s"' % escaped, PW_MARK_END])
    if out:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".lobbyui.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out).rstrip("\n") + "\n")
        os.replace(tmp, path)
    else:
        try:
            os.remove(path)
        except OSError:
            pass


def start_host(game, system, password=""):
    label = game.get("display") or game["name"]
    set_notice("正在建立主机：%s%s" % (label, " · 有密码" if password else ""), 6)
    with lock:
        state["host_exit"] = None
    started = False
    try:
        write_netplay_password(system, game, password)
    except Exception as exc:
        password = ""
        set_notice("写入房间密码失败，按无密码开房：%s" % exc, 6)
    try:
        started = launch_game(system, game,
                              ["-netplaymode", "host", "-netplayport", str(NETPLAY_PORT)])
    finally:
        try:
            write_netplay_password(system, game, "")
        except Exception:
            pass
        if started:
            with lock:
                state["host_exit"] = {"game": game["name"].lower(), "at": time.time()}
            set_notice("游戏已退出，房间公告约 %d 秒后从大厅消失" % int(ROOM_TTL), 6)


def find_local_game(game_name):
    gname = str(game_name or "").lower()
    with lock:
        systems = list(state["systems"])
    for system in systems:
        for game in system["games"]:
            if game["name"].lower() == gname:
                return game, system
    for system in systems:
        for game in system["games"]:
            if gname and gname in game["name"].lower():
                return game, system
    return None, None


def local_cover(game_name):
    with lock:
        systems = list(state["systems"])
    gname = str(game_name or "").lower()
    for system in systems:
        for game in system["games"]:
            if game["name"].lower() == gname:
                return game.get("cover")
    return None


def room_game_key(room):
    return str(room.get("game_name") or "").strip().lower()


def active_rooms(rooms):
    """同一游戏可能有多条公告，保留最新一条即可。"""
    result = {}
    for room in rooms:
        result.setdefault(room_game_key(room), room)
    return result


def room_is_mine(room):
    ip = local_ip()
    return bool(ip and str(room.get("ip") or "") == ip)


def display_name(game_name):
    game, _ = find_local_game(game_name)
    if game:
        return game.get("display") or game.get("name") or str(game_name)
    return str(game_name or "?")


def host_exit_badge(game_name):
    """本机刚退出、公告尚未过期时的剩余秒数；没有则返回 None。"""
    with lock:
        info = state.get("host_exit")
    if not info or info.get("game") != str(game_name).lower():
        return None
    left = ROOM_TTL - (time.time() - info["at"])
    return max(0, int(left)) if left > 0 else None


def start_join(room):
    game, system = find_local_game(room.get("game_name"))
    if not game:
        set_notice("本机缺少该游戏：%s" % (room.get("game_name") or "?"), 4)
        return
    label = game.get("display") or game["name"]
    if room.get("has_password"):
        set_notice("正在联机进入：%s · 该房间有密码" % label, 7)
    else:
        set_notice("正在联机进入：%s" % label, 6)
    launch_game(system, game, ["-netplaymode", "client", "-netplayip", str(room.get("ip")),
                               "-netplayport", str(int(room.get("port") or NETPLAY_PORT))])


def draw_header(screen, w, title, subtitle, f_title, f_sub, f_small, rooms_n, lobby_ms):
    screen.blit(f_title.render(title, True, TEXT), (60, 30))
    screen.blit(f_sub.render(subtitle, True, MUTED), (62, 96))
    extra = "%d 个房间在线" % rooms_n
    screen.blit(f_sub.render(extra, True, ACCENT), (w - 60 - f_sub.size(extra)[0], 44))
    lat = "大厅延迟 -" if lobby_ms is None else "大厅延迟 %.1f ms" % lobby_ms
    col = GREEN if (lobby_ms is not None and lobby_ms < 20) else MUTED
    screen.blit(f_small.render(lat, True, col), (w - 60 - f_small.size(lat)[0], 84))


def draw_footer(screen, w, h, footer_h, f_foot, help_txt, ip):
    pygame.draw.rect(screen, (15, 21, 29), pygame.Rect(0, h - footer_h, w, footer_h))
    info = "本机 %s · 端口 %d · v%s · ESC 返回系统" % (ip or "-", NETPLAY_PORT, VERSION)
    screen.blit(f_foot.render(info, True, MUTED), (60, h - footer_h + 24))
    screen.blit(f_foot.render(help_txt, True, MUTED), (w - 60 - f_foot.size(help_txt)[0], h - footer_h + 24))


def draw_notice(screen, w, h, footer_h, f_info):
    with lock:
        notice = state.get("notice")
    if not notice or notice["until"] < time.time():
        return
    txt = notice["text"]
    surf_font = fit_font(FONT_PATH, txt, 30, w - 200)
    label = surf_font.render(txt, True, TEXT)
    box = label.get_rect()
    box.inflate_ip(56, 34)
    box.center = (w // 2, h - footer_h - 90)
    pygame.draw.rect(screen, (32, 44, 58), box, border_radius=12)
    pygame.draw.rect(screen, AMBER, box, 2, border_radius=12)
    screen.blit(label, label.get_rect(center=box.center))


def card_frame(screen, rect, selected, color=CARD_EDGE):
    pygame.draw.rect(screen, CARD, rect, border_radius=14)
    pygame.draw.rect(screen, ACCENT if selected else color, rect, 4 if selected else 2, border_radius=14)


def draw_main(screen, w, h, header_h, footer_h, sel, f_title, f_sub, f_game, f_info, f_small, f_foot, systems, rooms, lobby_ms, ip):
    draw_header(screen, w, "联机大厅", "RetroArch Netplay · 自建服务器 10.144.144.3:80",
                f_title, f_sub, f_small, len(rooms), lobby_ms)
    area_y0, area_y1 = header_h + 10, h - footer_h - 20
    cw, ch, gap = 560, 380, 72
    total = cw * 2 + gap
    x0 = (w - total) // 2
    y = area_y0 + (area_y1 - area_y0 - ch) // 2
    total_games = sum(len(s["games"]) for s in systems)
    active_n = len(active_rooms(rooms))
    host_stat = "扫描中…" if not systems else "%d 款游戏可选" % total_games
    if systems and active_n:
        host_stat += " · %d 局已开启" % active_n
    cards = [
        (pygame.Rect(x0, y, cw, ch), HOST_C, "建立主机", "选择游戏开始一局对战\n房间自动发布到大厅",
         host_stat, "HOST"),
        (pygame.Rect(x0 + cw + gap, y, cw, ch), JOIN_C, "联机进入", "浏览在线房间\n实时测速 · 一键加入",
         "%d 个房间在线" % len(rooms), "JOIN"),
    ]
    for idx, (rect, color, title, desc, stat, tag) in enumerate(cards):
        selected = (idx == sel)
        card_frame(screen, rect, selected, color)
        tagf = pygame.font.Font(FONT_PATH, 22)
        screen.blit(tagf.render(tag, True, color), (rect.x + 34, rect.y + 28))
        tf = pygame.font.Font(FONT_PATH, 64)
        screen.blit(tf.render(title, True, TEXT), (rect.x + 32, rect.y + 82))
        for i, line in enumerate(desc.split("\n")):
            screen.blit(f_sub.render(line, True, MUTED), (rect.x + 36, rect.y + 190 + i * 36))
        pygame.draw.line(screen, (38, 50, 64), (rect.x + 32, rect.y + ch - 100),
                         (rect.right - 32, rect.y + ch - 100), 1)
        screen.blit(f_info.render(stat, True, color), (rect.x + 36, rect.y + ch - 76))
        if selected:
            hint = "按 Enter / A 进入"
            screen.blit(f_small.render(hint, True, ACCENT),
                        (rect.right - 34 - f_small.size(hint)[0], rect.y + ch - 72))
    draw_footer(screen, w, h, footer_h, f_foot, "← → 选择    Enter / A 确认", ip)


def draw_systems(screen, w, h, header_h, footer_h, sel, systems, f_title, f_sub, f_game, f_info, f_small, f_foot, rooms, lobby_ms, ip, ready):
    draw_header(screen, w, "建立主机", "选择平台 · 进入后挑选要对战的游戏",
                f_title, f_sub, f_small, len(rooms), lobby_ms)
    area_y0, area_y1 = header_h + 20, h - footer_h - 20
    if not systems:
        msg = "正在扫描游戏…" if not ready else "没有找到可联机的游戏"
        screen.blit(f_game.render(msg, True, MUTED), ((w - f_game.size(msg)[0]) // 2, (area_y0 + area_y1) // 2))
        draw_footer(screen, w, h, footer_h, f_foot, "ESC 返回主菜单", ip)
        return
    cols = min(3, max(1, len(systems)))
    rows = math.ceil(len(systems) / cols)
    gap = 36
    cw = min(560, (w - 2 * 60 - (cols - 1) * gap) // cols)
    ch = min(340, (area_y1 - area_y0 - (rows - 1) * gap) // rows)
    total_w = cols * cw + (cols - 1) * gap
    x0 = (w - total_w) // 2
    y0 = area_y0 + ((area_y1 - area_y0) - (rows * ch + (rows - 1) * gap)) // 2
    for idx, sysinfo in enumerate(systems):
        r, c = divmod(idx, cols)
        rect = pygame.Rect(x0 + c * (cw + gap), y0 + r * (ch + gap), cw, ch)
        card_frame(screen, rect, idx == sel)
        screen.blit(f_game.render(sysinfo["label"], True, TEXT), (rect.x + 26, rect.y + 24))
        active_keys = set(active_rooms(rooms))
        n_active = sum(1 for g in sysinfo["games"] if g["name"].lower() in active_keys)
        stat = "%d 款游戏" % len(sysinfo["games"])
        if n_active:
            stat += " · %d 局已开启" % n_active
        screen.blit(f_sub.render(stat, True, GREEN if n_active else MUTED),
                    (rect.x + 28, rect.y + 78))
        cover = sysinfo["games"][0]["cover"]
        img = load_cover(cover, (cw - 60, ch - 150)) if cover else None
        if img:
            screen.blit(img, (rect.x + (cw - img.get_width()) // 2,
                              rect.y + ch - 30 - img.get_height()))
    draw_footer(screen, w, h, footer_h, f_foot, "方向键选择    Enter / A 进入    ESC 返回", ip)


def draw_badge(screen, right, y, text, color, font, fg=(10, 16, 22)):
    tw, th = font.size(text)
    rect = pygame.Rect(right - tw - 20, y, tw + 20, th + 10)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    screen.blit(font.render(text, True, fg), (rect.x + 10, rect.y + 5))
    return rect.x


def draw_games(screen, w, h, header_h, footer_h, sel, system, f_title, f_sub, f_game, f_info, f_small, f_foot, rooms, lobby_ms, ip):
    draw_header(screen, w, system["label"], "选择游戏 · 建立房间 · 可设密码",
                f_title, f_sub, f_small, len(rooms), lobby_ms)
    games = system["games"]
    actives = active_rooms(rooms)
    area_y0, area_y1 = header_h + 20, h - footer_h - 20
    cols, rows = 4, 2
    per = cols * rows
    page = sel // per
    pages = max(1, math.ceil(len(games) / per))
    start = page * per
    chunk = games[start:start + per]
    gap = 26
    margin = 60
    cw = (w - 2 * margin - (cols - 1) * gap) // cols
    ch = min(360, (area_y1 - area_y0 - (rows - 1) * gap) // rows)
    total_w = cols * cw + (cols - 1) * gap
    x0 = (w - total_w) // 2
    for idx, game in enumerate(chunk):
        r, c = divmod(idx, cols)
        rect = pygame.Rect(x0 + c * (cw + gap), area_y0 + r * (ch + gap), cw, ch)
        card_frame(screen, rect, start + idx == sel)
        img_h = ch - 90
        img = load_cover(game["cover"], (cw - 30, img_h - 24))
        if img:
            screen.blit(img, (rect.x + (cw - img.get_width()) // 2,
                              rect.y + 12 + (img_h - 24 - img.get_height()) // 2))
        else:
            ph = pygame.Rect(rect.x + 15, rect.y + 12, cw - 30, img_h - 24)
            pygame.draw.rect(screen, (31, 43, 57), ph, border_radius=10)
            label = game.get("display") or game["name"]
            pf = fit_font(FONT_PATH, label, 34, ph.w - 20)
            screen.blit(pf.render(truncate(pf, label, ph.w - 20), True, MUTED),
                        (ph.x + (ph.w - pf.size(label)[0]) // 2, ph.y + ph.h // 2 - 18))
        label = game.get("display") or game["name"]
        nf = fit_font(FONT_PATH, label, 26, cw - 36)
        screen.blit(nf.render(truncate(nf, label, cw - 36), True, TEXT), (rect.x + 18, rect.y + ch - 66))
        room = actives.get(game["name"].lower())
        left = host_exit_badge(game["name"])
        bx = rect.right - 14
        if room and room_is_mine(room) and left is not None:
            draw_badge(screen, bx, rect.y + 14, "关闭中 %ds" % left, AMBER, f_small)
        elif room:
            if room.get("has_password"):
                bx = draw_badge(screen, bx, rect.y + 14, "有密码", AMBER, f_small) - 8
            if room_is_mine(room):
                bx = draw_badge(screen, bx, rect.y + 14, "本机", ACCENT, f_small) - 8
            draw_badge(screen, bx, rect.y + 14, "已开启", GREEN, f_small)
        elif left is not None:
            draw_badge(screen, bx, rect.y + 14, "关闭中 %ds" % left, AMBER, f_small)
    ptext = "%d / %d 页 · 共 %d 款" % (page + 1, pages, len(games))
    screen.blit(f_info.render(ptext, True, MUTED), (w - 60 - f_info.size(ptext)[0], header_h + 2))
    draw_footer(screen, w, h, footer_h, f_foot, "方向键选择    Enter / A 建立房间    ESC 返回", ip)


OSK_ROWS = ["1234567890", "abcdefghij", "klmnopqrst", "uvwxyz-_.:"]
OSK_ACTIONS = ["退格", "清空", "开始"]


def draw_password(screen, w, h, header_h, footer_h, text, row, col, nav, system, game,
                  f_title, f_sub, f_game, f_info, f_small, f_foot, rooms, lobby_ms, ip):
    draw_header(screen, w, "建立主机 · 房间密码", "留空即无密码 · 有密码时对方加入需输入",
                f_title, f_sub, f_small, len(rooms), lobby_ms)
    area_y0, area_y1 = header_h + 24, h - footer_h - 20
    label = game.get("display") or game["name"]
    screen.blit(f_game.render("%s · %s" % (system["label"], truncate(f_game, label, w - 240)), True, TEXT),
                (60, area_y0))
    pw_rect = pygame.Rect(60, area_y0 + 62, w - 120, 88)
    pygame.draw.rect(screen, (17, 24, 33), pw_rect, border_radius=12)
    pygame.draw.rect(screen, ACCENT if text else CARD_EDGE, pw_rect, 3, border_radius=12)
    shown = text if text else "（无密码）"
    screen.blit(f_sub.render(truncate(f_sub, shown, pw_rect.w - 40), True, TEXT if text else MUTED),
                (pw_rect.x + 24, pw_rect.y + 28))
    count = "%d / %d" % (len(text), PASSWORD_MAX)
    screen.blit(f_small.render(count, True, MUTED),
                (pw_rect.right - 24 - f_small.size(count)[0], pw_rect.y + 34))

    key_w, key_h, gap = 74, 64, 12
    total_w = 10 * key_w + 9 * gap
    x0 = (w - total_w) // 2
    y0 = pw_rect.bottom + 46
    for r, chars in enumerate(OSK_ROWS):
        for c, ch in enumerate(chars):
            rect = pygame.Rect(x0 + c * (key_w + gap), y0 + r * (key_h + gap), key_w, key_h)
            selected = nav and row == r and col == c
            pygame.draw.rect(screen, (31, 43, 57), rect, border_radius=10)
            pygame.draw.rect(screen, ACCENT if selected else CARD_EDGE, rect, 3 if selected else 1,
                             border_radius=10)
            screen.blit(f_game.render(ch, True, TEXT), (rect.centerx - f_game.size(ch)[0] // 2,
                                                        rect.centery - f_game.size(ch)[1] // 2))
    aw, agap = 220, 24
    atotal = len(OSK_ACTIONS) * aw + (len(OSK_ACTIONS) - 1) * agap
    ax0 = (w - atotal) // 2
    ay = y0 + 4 * (key_h + gap) + 12
    for i, act in enumerate(OSK_ACTIONS):
        rect = pygame.Rect(ax0 + i * (aw + agap), ay, aw, 66)
        selected = nav and row == 4 and col == i
        base = (31, 43, 57) if act != "开始" else (27, 66, 39)
        pygame.draw.rect(screen, base, rect, border_radius=10)
        pygame.draw.rect(screen, ACCENT if selected else (GREEN if act == "开始" else CARD_EDGE),
                         rect, 3 if selected else 1, border_radius=10)
        colr = TEXT if act != "开始" else GREEN
        screen.blit(f_sub.render(act, True, colr), (rect.centerx - f_sub.size(act)[0] // 2,
                                                   rect.centery - f_sub.size(act)[1] // 2))
    hint = "直接打字或方向键选择 · Enter %s · ESC 返回" % ("开始" if not nav else "确认")
    draw_footer(screen, w, h, footer_h, f_foot, hint, ip)


def draw_rooms(screen, w, h, header_h, footer_h, sel, rooms, err, rtt, peers, f_title, f_sub, f_game, f_info, f_small, f_foot, lobby_ms, ip):
    draw_header(screen, w, "联机进入", "在线房间 · 主机退出后房间约 60 秒自动消失",
                f_title, f_sub, f_small, len(rooms), lobby_ms)
    area_y0, area_y1 = header_h, h - footer_h
    margin, gap = 48, 28
    if not rooms:
        msg = "暂无房间在线" if not err else "大厅连接失败"
        screen.blit(f_game.render(msg, True, MUTED), ((w - f_game.size(msg)[0]) // 2, (area_y0 + area_y1) // 2 - 40))
        hint = "在另一台机器上使用「建立主机」即可出现在这里" if not err else err[:90]
        screen.blit(f_small.render(hint, True, MUTED), ((w - f_small.size(hint)[0]) // 2, (area_y0 + area_y1) // 2 + 10))
        draw_footer(screen, w, h, footer_h, f_foot, "R 刷新    ESC 返回", ip)
        return
    cols = min(4, max(1, len(rooms)))
    rows = math.ceil(len(rooms) / cols)
    card_w = min(460, (w - 2 * margin - (cols - 1) * gap) // cols)
    card_h = min(560, (area_y1 - area_y0 - (rows - 1) * gap) // rows)
    total_w = cols * card_w + (cols - 1) * gap
    x0 = (w - total_w) // 2
    for idx, room in enumerate(rooms):
        r, c = divmod(idx, cols)
        x = x0 + c * (card_w + gap)
        y = area_y0 + r * (card_h + gap)
        rect = pygame.Rect(x, y, card_w, card_h)
        ok = bool(room.get("connectable"))
        border = GREEN if ok else RED
        pygame.draw.rect(screen, CARD, rect, border_radius=14)
        pygame.draw.rect(screen, ACCENT if idx == sel else border, rect, 4 if idx == sel else 2, border_radius=14)
        img_h = int(card_h * 0.58)
        box = (card_w - 40, img_h - 24)
        raw_game = str(room.get("game_name") or "?")
        game = display_name(raw_game)
        cover = load_cover(local_cover(raw_game), box)
        if cover is None:
            ph = pygame.Rect(x + 20, y + 16, card_w - 40, img_h - 24)
            pygame.draw.rect(screen, (31, 43, 57), ph, border_radius=10)
            f_ph = fit_font(FONT_PATH, game, 40, ph.w - 20)
            screen.blit(f_ph.render(truncate(f_ph, game, ph.w - 20), True, MUTED),
                        (ph.x + (ph.w - f_ph.size(game)[0]) // 2, ph.y + ph.h // 2 - 20))
        else:
            screen.blit(cover, (x + (card_w - cover.get_width()) // 2,
                                y + 16 + (img_h - 24 - cover.get_height()) // 2))
        bx = rect.right - 12
        if room.get("has_password"):
            bx = draw_badge(screen, bx, rect.y + 12, "有密码", AMBER, f_small) - 8
        if room_is_mine(room):
            left = host_exit_badge(raw_game)
            if left is not None:
                draw_badge(screen, bx, rect.y + 12, "关闭中 %ds" % left, AMBER, f_small)
            else:
                draw_badge(screen, bx, rect.y + 12, "本机", ACCENT, f_small)
        tx = x + 22
        ty = y + img_h + 8
        f_name = fit_font(FONT_PATH, game, 34, card_w - 44)
        screen.blit(f_name.render(truncate(f_name, game, card_w - 44), True, TEXT), (tx, ty))
        user = str(room.get("username") or "-")
        core = str(room.get("core_name") or "-")
        line2 = truncate(f_info, "%s · %s" % (user, core), card_w - 44)
        screen.blit(f_info.render(line2, True, MUTED), (tx, ty + 44))
        players = room.get("player_count", 0)
        line3 = "玩家 %s · %s:%s" % (players, room.get("ip"), room.get("port"))
        screen.blit(f_small.render(truncate(f_small, line3, card_w - 44), True, MUTED), (tx, ty + 78))
        dot_y = y + card_h - 34
        pygame.draw.circle(screen, border, (tx + 7, dot_y + 9), 6)
        st = "可连接" if ok else "不可达"
        screen.blit(f_small.render(st, True, border), (tx + 20, dot_y))
        ms = rtt.get(room.get("id"))
        peer = peers.get(str(room.get("ip") or ""))
        cost = peer["cost"] if peer else ""
        if cost == "p2p":
            label, lat, ms_color = "P2P", peer["lat"], GREEN
        elif cost.startswith("relay"):
            label, lat, ms_color = "中继", peer["lat"], AMBER
        elif cost == "local":
            label, lat, ms_color = "本机", None, ACCENT
        else:
            label, lat, ms_color = "测速", ms, GREEN if (ms is not None and ms < 30) else MUTED
        ms_txt = label if lat is None else "%s %.1f ms" % (label, lat)
        screen.blit(f_small.render(ms_txt, True, ms_color),
                    (x + card_w - 22 - f_small.size(ms_txt)[0], dot_y))
    draw_footer(screen, w, h, footer_h, f_foot,
                "方向键选择    Enter / A 加入    R 刷新    P2P=直连  中继=中转    ESC 返回", ip)


def main():
    # 单实例：ES 磁贴与 lobby_watch 可能同时拉起 UI，第二个直接退出
    instance_fd = os.open(INSTANCE_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(instance_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(instance_fd)
        return
    os.ftruncate(instance_fd, 0)
    os.write(instance_fd, str(os.getpid()).encode())
    pygame.init()
    info = pygame.display.Info()
    w, h = info.current_w or 1920, info.current_h or 1080
    screen = pygame.display.set_mode((w, h), pygame.FULLSCREEN)
    pygame.display.set_caption("联机大厅")
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    bg = pygame.Surface((w, h))
    for y in range(h):
        t = y / max(1, h - 1)
        pygame.draw.line(bg, tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)), (0, y), (w, y))
    f_title = pygame.font.Font(FONT_PATH, 54)
    f_sub = pygame.font.Font(FONT_PATH, 24)
    f_game = pygame.font.Font(FONT_PATH, 34)
    f_info = pygame.font.Font(FONT_PATH, 22)
    f_small = pygame.font.Font(FONT_PATH, 19)
    f_foot = pygame.font.Font(FONT_PATH, 21)
    threading.Thread(target=fetch_rooms, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    focus_self(0.3)
    header_h, footer_h = 150, 78
    page = "main"
    sel_main = 0
    sel_sys = 0
    sel_game = 0
    sel_room = 0
    pw_text = ""
    pw_row, pw_col, pw_nav = 4, 2, True
    running = True
    while running:
        with lock:
            rooms = list(state["rooms"])
            err = state["error"]
            rtt = dict(state["rtt"])
            peers = dict(state["peers"])
            lobby_ms = state["lobby_ms"]
            systems = list(state["systems"])
            ready = state["systems_ready"]
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                key = event.key
                if key == pygame.K_r and page in ("rooms", "main"):
                    refresh_evt.set()
                elif key == pygame.K_ESCAPE:
                    if page == "main":
                        running = False
                    elif page == "password":
                        page = "games"
                    elif page == "games":
                        page = "systems"
                    else:
                        page = "main"
                elif key == pygame.K_q and page == "main":
                    running = False
                elif page == "main":
                    if key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
                        sel_main = 1 - sel_main
                    elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_z):
                        if sel_main == 0:
                            page = "systems"
                            sel_sys = 0
                        else:
                            page = "rooms"
                            sel_room = 0
                elif page == "systems":
                    if systems:
                        if key in (pygame.K_LEFT, pygame.K_a):
                            sel_sys = (sel_sys - 1) % len(systems)
                        elif key in (pygame.K_RIGHT, pygame.K_d):
                            sel_sys = (sel_sys + 1) % len(systems)
                        elif key in (pygame.K_UP, pygame.K_w):
                            sel_sys = (sel_sys - 3) % len(systems)
                        elif key in (pygame.K_DOWN, pygame.K_s):
                            sel_sys = (sel_sys + 3) % len(systems)
                        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_z):
                            page = "games"
                            sel_game = 0
                elif page == "games":
                    system = systems[sel_sys]
                    n = len(system["games"])
                    if key in (pygame.K_LEFT, pygame.K_a):
                        sel_game = (sel_game - 1) % n
                    elif key in (pygame.K_RIGHT, pygame.K_d):
                        sel_game = (sel_game + 1) % n
                    elif key in (pygame.K_UP, pygame.K_w):
                        sel_game = (sel_game - 4) % n
                    elif key in (pygame.K_DOWN, pygame.K_s):
                        sel_game = (sel_game + 4) % n
                    elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_z):
                        pw_text = ""
                        pw_row, pw_col, pw_nav = 4, 2, True
                        page = "password"
                elif page == "password":
                    system = systems[sel_sys]
                    n_cols = len(OSK_ROWS[pw_row]) if pw_row < 4 else len(OSK_ACTIONS)
                    if key == pygame.K_LEFT:
                        pw_nav = True
                        pw_col = (pw_col - 1) % n_cols
                    elif key == pygame.K_RIGHT:
                        pw_nav = True
                        pw_col = (pw_col + 1) % n_cols
                    elif key == pygame.K_UP:
                        pw_nav = True
                        pw_row = max(0, pw_row - 1)
                        pw_col = min(pw_col, len(OSK_ROWS[pw_row]) - 1)
                    elif key == pygame.K_DOWN:
                        pw_nav = True
                        pw_row = min(4, pw_row + 1)
                        pw_col = min(pw_col, (len(OSK_ROWS[pw_row]) - 1) if pw_row < 4
                                     else len(OSK_ACTIONS) - 1)
                    elif key == pygame.K_BACKSPACE:
                        pw_text = pw_text[:-1]
                        pw_nav = False
                    elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        start = not pw_nav
                        if pw_nav and pw_row < 4:
                            if len(pw_text) < PASSWORD_MAX:
                                pw_text += OSK_ROWS[pw_row][pw_col]
                        elif pw_nav:
                            action = OSK_ACTIONS[pw_col]
                            if action == "退格":
                                pw_text = pw_text[:-1]
                            elif action == "清空":
                                pw_text = ""
                            else:
                                start = True
                        if start:
                            game = system["games"][sel_game]
                            page = "games"
                            start_host(game, system, pw_text)
                            pw_text = ""
                    else:
                        ch = event.unicode
                        if ch and 32 <= ord(ch) < 127 and ch not in '"\\' \
                                and len(pw_text) < PASSWORD_MAX:
                            pw_text += ch
                            pw_nav = False
                elif page == "rooms":
                    n = len(rooms)
                    if n:
                        cols = min(4, max(1, n))
                        if key in (pygame.K_LEFT, pygame.K_a):
                            sel_room = (sel_room - 1) % n
                        elif key in (pygame.K_RIGHT, pygame.K_d):
                            sel_room = (sel_room + 1) % n
                        elif key in (pygame.K_UP, pygame.K_w):
                            sel_room = (sel_room - cols) % n
                        elif key in (pygame.K_DOWN, pygame.K_s):
                            sel_room = (sel_room + cols) % n
                        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_z):
                            room = rooms[sel_room]
                            if room.get("connectable"):
                                start_join(room)
                            else:
                                set_notice("该房间当前不可连接", 3)
        if page in ("systems", "games", "password") and not systems:
            page = "main"
        screen.blit(bg, (0, 0))
        if page == "main":
            draw_main(screen, w, h, header_h, footer_h, sel_main, f_title, f_sub, f_game, f_info,
                      f_small, f_foot, systems, rooms, lobby_ms, local_ip())
        elif page == "systems":
            if sel_sys >= len(systems):
                sel_sys = 0
            draw_systems(screen, w, h, header_h, footer_h, sel_sys, systems, f_title, f_sub, f_game,
                         f_info, f_small, f_foot, rooms, lobby_ms, local_ip(), ready)
        elif page == "games":
            system = systems[sel_sys]
            draw_games(screen, w, h, header_h, footer_h, sel_game, system, f_title, f_sub, f_game,
                       f_info, f_small, f_foot, rooms, lobby_ms, local_ip())
        elif page == "password":
            system = systems[sel_sys]
            draw_password(screen, w, h, header_h, footer_h, pw_text, pw_row, pw_col, pw_nav,
                          system, system["games"][sel_game], f_title, f_sub, f_game,
                          f_info, f_small, f_foot, rooms, lobby_ms, local_ip())
        elif page == "rooms":
            if sel_room >= len(rooms):
                sel_room = 0
            draw_rooms(screen, w, h, header_h, footer_h, sel_room, rooms, err, rtt, peers, f_title,
                       f_sub, f_game, f_info, f_small, f_foot, lobby_ms, local_ip())
        draw_notice(screen, w, h, footer_h, f_info)
        pygame.display.flip()
        clock.tick(20)
    stop_evt.set()
    pygame.quit()


if __name__ == "__main__":
    main()
