#!/usr/bin/env python3
"""从 GitHub 拉取大厅更新并原子替换本地文件。

用法（Batocera 上 root 执行）：
  lobby-update             # 检查并安装最新版
  lobby-update --check     # 只检查，不安装
  lobby-update --force     # 版本相同也重装
  lobby-update --repo owner/repo
  lobby-update --branch main

仓库地址默认从 /userdata/system/lobby-ui/update_repo 读取（内容形如 owner/repo）。
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

BASE = "/userdata/system/lobby-ui"
SERVICES = "/userdata/system/services"
ES_CONFIGS = "/userdata/system/configs/emulationstation"
ROMS_LOBBY = "/userdata/roms/lobby"
REPO_FILE = os.path.join(BASE, "update_repo")
VERSION_FILE = os.path.join(BASE, "VERSION")
ASSET_NAME = "lobby-ui.tar.gz"
MIRRORS = ("https://ghfast.top/%s", "https://gh-proxy.com/%s")


def log(msg):
    print(msg, flush=True)


def read_version(root=None):
    path = os.path.join(root, "VERSION") if root else VERSION_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def read_repo(arg):
    if arg:
        return arg.strip().strip("/")
    try:
        with open(REPO_FILE, encoding="utf-8") as fh:
            return fh.read().strip().strip("/")
    except OSError:
        return ""


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "batocera-lobby-update"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download(url):
    errors = []
    candidates = [url] + [m % url for m in MIRRORS]
    for candidate in candidates:
        try:
            log("下载 %s" % candidate)
            data = fetch(candidate, timeout=90)
            if len(data) < 1024:
                raise RuntimeError("文件过小：%d 字节" % len(data))
            return data, candidate
        except Exception as exc:
            errors.append("%s: %s" % (candidate, exc))
    raise RuntimeError("下载失败：\n" + "\n".join(errors))


def extract_payload(data):
    tmp = tempfile.mkdtemp(prefix="lobby-update-")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise RuntimeError("压缩包包含非法路径：%s" % name)
        try:
            tar.extractall(tmp, filter="data")
        except TypeError:
            tar.extractall(tmp)
    # GitHub 源码包会多一层目录；release 包可能直接是根目录
    roots = [tmp]
    roots += [os.path.join(tmp, entry) for entry in sorted(os.listdir(tmp))
              if os.path.isdir(os.path.join(tmp, entry))]
    for root in roots:
        if (os.path.isfile(os.path.join(root, "src", "lobby_ui.py"))
                and os.path.isfile(os.path.join(root, "VERSION"))):
            return tmp, root
    for root in roots:
        if (os.path.isfile(os.path.join(root, "lobby_ui.py"))
                and os.path.isfile(os.path.join(root, "VERSION"))):
            return tmp, root
    shutil.rmtree(tmp, ignore_errors=True)
    raise RuntimeError("压缩包里没有找到 src/lobby_ui.py 与 VERSION")


def install_file(src, dst, mode=0o644):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".update.tmp"
    shutil.copyfile(src, tmp)
    os.chmod(tmp, mode)
    os.replace(tmp, dst)


def install_payload(root):
    pairs = []
    for name in ("lobby_ui.py", "lobby_watch.py", "update.py", "uinput_keys.py"):
        for sub in ("src", "tools", "."):
            src = os.path.join(root, sub, name) if sub != "." else os.path.join(root, name)
            if os.path.isfile(src):
                pairs.append((src, os.path.join(BASE, name), 0o755))
                break
    for name in ("es_launch.sh", "lobby.png", "gamelist.xml", "lobby-cover.jpg"):
        src = os.path.join(root, "es", name)
        if os.path.isfile(src):
            pairs.append((src, os.path.join(BASE, name), 0o644))
    pairs.append((os.path.join(root, "VERSION"), VERSION_FILE, 0o644))
    for name in ("lobby_home", "lobby_enter"):
        src = os.path.join(root, "services", name)
        if os.path.isfile(src):
            pairs.append((src, os.path.join(SERVICES, name), 0o755))
    es_cfg = os.path.join(root, "es", "es_systems_lobby.cfg")
    if os.path.isfile(es_cfg):
        pairs.append((es_cfg, os.path.join(ES_CONFIGS, "es_systems_lobby.cfg"), 0o644))
    for src, dst, mode in pairs:
        if not os.path.isfile(src):
            log("跳过缺失文件 %s" % src)
            continue
        install_file(src, dst, mode)
    # 大厅磁贴载荷
    for name, dst in (("gamelist.xml", os.path.join(ROMS_LOBBY, "gamelist.xml")),
                      ("lobby-cover.jpg", os.path.join(ROMS_LOBBY, "images", "联机大厅-image.jpg"))):
        src = os.path.join(root, "es", name)
        if os.path.isfile(src):
            install_file(src, dst, 0o644)
    os.makedirs(os.path.join(ROMS_LOBBY, "images"), exist_ok=True)
    open(os.path.join(ROMS_LOBBY, "联机大厅.lobby"), "a").close()
    # 主题 logo 由 boot-custom.sh 在开机时恢复，这里也补一次
    logo = os.path.join(BASE, "lobby.png")
    logo_dst = "/usr/share/emulationstation/themes/es-theme-carbon/art/logos/lobby.png"
    if os.path.isfile(logo) and os.path.isdir(os.path.dirname(logo_dst)):
        try:
            install_file(logo, logo_dst, 0o644)
        except OSError:
            pass


def restart_ui():
    def run(cmd, **kw):
        try:
            subprocess.run(cmd, shell=True, timeout=20, **kw)
        except Exception as exc:
            log("命令失败：%s (%s)" % (cmd, exc))

    def running(pattern):
        return subprocess.call("pgrep -f '%s' >/dev/null 2>&1" % pattern, shell=True) == 0

    # batocera-services status 在部分机器上会卡住，直接管理两个进程
    if running("lobby_watch\\.py"):
        run("pkill -f 'lobby_watch\\.py' || true")
        run("nohup setsid /userdata/system/services/lobby_enter start "
            ">/dev/null 2>&1 &")
    if running("lobby_ui\\.py"):
        run("pkill -f 'lobby_ui\\.py' || true")
        run("nohup setsid /userdata/system/services/lobby_home start "
            ">/dev/null 2>&1 &")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查版本")
    ap.add_argument("--force", action="store_true", help="版本相同也重新安装")
    ap.add_argument("--repo", default="", help="GitHub owner/repo")
    ap.add_argument("--branch", default="main", help="源码分支（无 release 时使用）")
    ap.add_argument("--asset-url", default="", help="直接指定 tarball URL")
    args = ap.parse_args()

    repo = read_repo(args.repo)
    if not repo and not args.asset_url:
        log("未配置更新仓库。请把 owner/repo 写入 %s，或使用 --repo。" % REPO_FILE)
        return 2

    local_v = read_version()
    log("本地版本：%s" % (local_v or "unknown"))

    asset_url = args.asset_url or (
        "https://github.com/%s/releases/latest/download/%s" % (repo, ASSET_NAME))
    data = None
    source = ""
    try:
        data, source = download(asset_url)
    except Exception as exc:
        if not repo:
            log("下载失败：%s" % exc)
            return 1
        log("Release 不可用（%s），改用分支源码包。" % str(exc).splitlines()[0])
        branch_url = "https://github.com/%s/archive/refs/heads/%s.tar.gz" % (repo, args.branch)
        data, source = download(branch_url)

    tmp, root = extract_payload(data)
    remote_v = read_version(root)
    log("远端版本：%s（%s）" % (remote_v or "unknown", source))
    if not remote_v:
        log("远端缺少 VERSION 文件，拒绝安装。")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    if args.check:
        if remote_v == local_v:
            log("已是最新版本。")
        else:
            log("可更新：%s -> %s。执行 lobby-update 安装。" % (local_v or "?", remote_v))
        shutil.rmtree(tmp, ignore_errors=True)
        return 0
    if remote_v == local_v and not args.force:
        log("已是最新版本（--force 可强制重装）。")
        shutil.rmtree(tmp, ignore_errors=True)
        return 0

    install_payload(root)
    shutil.rmtree(tmp, ignore_errors=True)
    log("已更新到 %s，正在重启大厅界面…" % remote_v)
    restart_ui()
    log("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
