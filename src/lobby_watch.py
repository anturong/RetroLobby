#!/usr/bin/env python3
"""Open the lobby UI as soon as ES shows the 联机大厅 game list.

ES has no hook for entering a system, so this watches the screen: the
game-list preview box (right pane) must match our cover image.  Matching
uses a 40x28 grayscale NCC, which is ~0.99 on the game list and ~0.00 on
the ES home screen (the cover is also used as the system background there,
but zoomed).

The UI may be exited back onto the same game list, so re-arming waits for
two consecutive low scores (teardown can leave one stale frame) and every
UI exit sends Escape to ES unconditionally: there is no compositor, so the
framebuffer may still show the dead UI frame until ES repaints.
"""
import math
import os
import subprocess
import sys
import time

import pygame

HERE = "/userdata/system/lobby-ui"
UI = os.path.join(HERE, "lobby_ui.py")
COVER = os.path.join(HERE, "lobby-cover.jpg")
SHOT = "/tmp/lobby_watch.png"
UI_LOG = "/userdata/system/logs/lobby_ui.log"
LOG = "/userdata/system/logs/lobby_watch.log"
ENV = dict(os.environ)
ENV.update(DISPLAY=":0", HOME="/userdata/system", XDG_CONFIG_HOME="/userdata/system/configs")
DEBUG = os.environ.get("LOBBY_WATCH_DEBUG") == "1"

# Preview box of the carbon gamelist, as fractions of the screen.
RECT = (0.552, 0.222, 0.927, 0.676)
THUMB = (40, 28)
THRESHOLD = 0.80
POLL = 1.0
CAPTURE_W = 240


def log(msg):
    try:
        with open(LOG, "a") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def screen_size():
    try:
        out = subprocess.check_output(["xrandr", "--current"], env=ENV,
                                      stderr=subprocess.DEVNULL, timeout=3).decode()
        for line in out.splitlines():
            if line.startswith("Screen 0:") and "current" in line:
                w, h = line.split("current", 1)[1].split(",")[0].split("x")
                return int(w), int(h)
    except Exception:
        pass
    return 1920, 1080


def gray_thumb(surf, size):
    surf = pygame.transform.smoothscale(surf, size)
    w, h = size
    vals = []
    for y in range(h):
        for x in range(w):
            c = surf.get_at((x, y))
            vals.append(0.299 * c.r + 0.587 * c.g + 0.114 * c.b)
    return vals


def ncc(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    va = [x - ma for x in a]
    vb = [y - mb for y in b]
    den = math.sqrt(sum(x * x for x in va)) * math.sqrt(sum(y * y for y in vb))
    return sum(x * y for x, y in zip(va, vb)) / den if den > 1e-6 else 0.0


def cover_ref():
    img = pygame.image.load(COVER)
    return gray_thumb(img, THUMB)


def region(size):
    w, h = size
    return (int(w * RECT[0]) & ~1, int(h * RECT[1]) & ~1,
            int(w * RECT[2]) & ~1, int(h * RECT[3]) & ~1)


def score_shot(ref):
    return ncc(gray_thumb(pygame.image.load(SHOT), THUMB), ref)


def score_full(path, ref):
    img = pygame.image.load(path)
    w, h = img.get_size()
    x0, y0 = int(w * RECT[0]), int(h * RECT[1])
    x1, y1 = int(w * RECT[2]), int(h * RECT[3])
    sub = img.subsurface((x0, y0, x1 - x0, y1 - y0))
    return ncc(gray_thumb(sub, THUMB), ref)


def capture(size):
    # 只抓预览框那块，整屏 XGetImage 在 vmwgfx 下会拖垮驱动
    x0, y0, x1, y1 = region(size)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "x11grab",
                    "-video_size", "%dx%d" % (x1 - x0, y1 - y0),
                    "-i", ":0.0+%d,%d" % (x0, y0),
                    "-vf", "scale=%d:-2" % CAPTURE_W, "-frames:v", "1", "-y", SHOT],
                   env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    return os.path.isfile(SHOT)


def proc_has(needle):
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                if needle.encode() in fh.read():
                    return True
        except OSError:
            continue
    return False


def ui_running():
    return proc_has("lobby_ui.py")


def busy():
    return (proc_has("lobby_ui.py") or proc_has("/usr/bin/retroarch")
            or proc_has("/usr/bin/emulatorlauncher"))


def open_ui():
    log("match; opening lobby ui")
    started = time.time()
    with open(UI_LOG, "ab") as fh:
        proc = subprocess.Popen(["/usr/bin/python3", UI], env=ENV, stdout=fh, stderr=fh)
        code = proc.wait()
    lived = time.time() - started
    log("lobby ui exited (%s) after %.1fs" % (code, lived))
    return lived


def es_window():
    try:
        out = subprocess.run(["xdotool", "search", "--class", "emulationstation"],
                             env=ENV, capture_output=True, timeout=3).stdout.split()
        return out[0].decode() if out else ""
    except Exception:
        return ""


def back_to_home(size, ref):
    # We opened the UI from the game list; on exit ES returns to that list.
    # ESC there goes back to the home carousel.  Send the key first: without a
    # compositor the framebuffer keeps the dead UI frame until ES repaints, so
    # a pre-key capture always looks like "not the gamelist".
    time.sleep(0.3)
    for attempt in range(3):
        wid = es_window()
        if wid:
            subprocess.run(["xdotool", "windowactivate", "--sync", wid], env=ENV, timeout=4,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("sending ESC to ES (try %d)" % (attempt + 1))
        subprocess.run(["xdotool", "key", "--clearmodifiers", "Escape"], env=ENV, timeout=4,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.7)
        try:
            if not capture(size) or score_shot(ref) < THRESHOLD:
                return
        except Exception:
            return
    log("still on ES gamelist after ESC")


def selftest(paths):
    ref = cover_ref()
    for p in paths:
        print("%.3f %s" % (score_full(p, ref), p))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest(sys.argv[2:])
    if not os.path.isfile(UI) or not os.path.isfile(COVER):
        log("missing %s or %s; exit" % (UI, COVER))
        return 1
    size = screen_size()
    ref = cover_ref()
    log("watching for lobby gamelist (screen %dx%d)" % size)
    armed = True
    low = 0
    while True:
        try:
            if busy():
                time.sleep(0.5)
                continue
            if not capture(size):
                time.sleep(POLL)
                continue
            s = score_shot(ref)
            if DEBUG:
                log("score %.3f armed=%s" % (s, armed))
            if s < THRESHOLD:
                # Require a stable low before re-arming: the teardown of the
                # pygame window can leave one stale frame of the gamelist.
                low += 1
                if low >= 2:
                    armed = True
            elif armed:
                low = 0
                armed = False
                # ES 自己的磁贴命令可能同时也启动了 UI（用户连按 A）
                time.sleep(0.6)
                if ui_running():
                    log("ui already running (ES launch); waiting")
                    while ui_running():
                        time.sleep(0.5)
                else:
                    lived = open_ui()
                    # 单实例锁让重复 UI 立刻退出；此时别再给 ES 发 ESC
                    if lived < 2.0 and ui_running():
                        log("another ui instance is running; skip ESC")
                        continue
                back_to_home(size, ref)
        except Exception as exc:
            log("watch error: %r" % (exc,))
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
