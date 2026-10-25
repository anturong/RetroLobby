#!/usr/bin/env python3
"""把 lobby-ui 部署到一台 Batocera 43.1（经 SSH/SFTP）。

用法：
  python deploy.py --host 192.168.232.129 --nick bato-n305 --node-ip 10.144.144.3 --lobby-server
  python deploy.py --host 192.168.232.130 --nick bato-n305-2

默认密码 linux，可用 --password 覆盖。安装完成后重启目标机生效。
SFTP 在 Batocera 上以 /userdata/system 为根，故全部使用相对路径。
"""
import argparse
import base64
import hashlib
import os
import sys

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))


def put(sftp, local_rel, remote_rel):
    path = os.path.join(HERE, local_rel)
    with open(path, "rb") as fh:
        data = fh.read()
    with sftp.open(remote_rel, "wb") as fh:
        fh.write(data)
    print("put", remote_rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--nick", required=True, help="联机昵称，例如 bato-n305")
    ap.add_argument("--node-ip", default="", help="本机 EasyTier 虚拟 IP，用于 es_launch 外的展示（可选）")
    ap.add_argument("--lobby-ip", default="10.144.144.3", help="大厅服务器虚拟 IP")
    ap.add_argument("--lobby-server", action="store_true", help="本机同时运行 netplay-lobby-server-go")
    ap.add_argument("--update-repo", default="", help="GitHub owner/repo，供 lobby-update 使用")
    ap.add_argument("--password", default="linux")
    args = ap.parse_args()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(args.host, username="root", password=args.password, timeout=15,
              look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()

    def ssh(cmd):
        _in, out, err = c.exec_command(cmd, timeout=60)
        code = out.channel.recv_exit_status()
        text = out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")
        if code != 0:
            raise RuntimeError("command failed (%d): %s\n%s" % (code, cmd, text))
        return text

    ssh("mkdir -p /userdata/system/lobby-ui /userdata/system/configs/emulationstation "
        "/userdata/roms/lobby/images /userdata/system/logs")

    put(sftp, "src/lobby_ui.py", "lobby-ui/lobby_ui.py")
    put(sftp, "src/lobby_watch.py", "lobby-ui/lobby_watch.py")
    put(sftp, "src/update.py", "lobby-ui/update.py")
    put(sftp, "VERSION", "lobby-ui/VERSION")
    put(sftp, "tools/uinput_keys.py", "lobby-ui/uinput_keys.py")
    put(sftp, "es/es_launch.sh", "lobby-ui/es_launch.sh")
    put(sftp, "es/lobby.png", "lobby-ui/lobby.png")
    put(sftp, "es/es_systems_lobby.cfg", "configs/emulationstation/es_systems_lobby.cfg")
    put(sftp, "es/gamelist.xml", "lobby-ui/gamelist.xml")
    put(sftp, "es/lobby-cover.jpg", "lobby-ui/lobby-cover.jpg")

    # SFTP 以 /userdata/system 为根，跨目录移动交给 shell；
    # lobby-ui/lobby-cover.jpg 留一份给 lobby_watch.py 做画面识别
    ssh("mv -f /userdata/system/lobby-ui/gamelist.xml /userdata/roms/lobby/gamelist.xml; "
        "cp -f /userdata/system/lobby-ui/lobby-cover.jpg '/userdata/roms/lobby/images/联机大厅-image.jpg'; "
        ": > '/userdata/roms/lobby/联机大厅.lobby'")

    put(sftp, "services/lobby_home", "services/lobby_home")
    put(sftp, "services/lobby_enter", "services/lobby_enter")
    services = "lobby_home lobby_enter"
    restart_server = False
    if args.lobby_server:
        put(sftp, "services/netplay_lobby", "services/netplay_lobby")
        services += " netplay_lobby"
        ssh("mkdir -p /userdata/system/netplay-lobby/config "
            "/userdata/system/netplay-lobby/web/templates /userdata/system/netplay-lobby/geoip2")
        # 运行中的二进制无法覆盖（ETXTBSY），只有内容变化时才停服更新
        with open(os.path.join(HERE, "lobby-server/netplay-lobby-server-go"), "rb") as fh:
            local_md5 = hashlib.md5(fh.read()).hexdigest()
        remote_md5 = ssh("md5sum /userdata/system/netplay-lobby/netplay-lobby-server-go "
                         "2>/dev/null | cut -d' ' -f1").strip()
        if remote_md5 != local_md5:
            ssh("batocera-services stop netplay_lobby >/dev/null 2>&1 || true")
            put(sftp, "lobby-server/netplay-lobby-server-go", "netplay-lobby/netplay-lobby-server-go")
            restart_server = True
        put(sftp, "lobby-server/config/lobby.yaml", "netplay-lobby/config/lobby.yaml")
        put(sftp, "lobby-server/web/templates/index.html", "netplay-lobby/web/templates/index.html")
        put(sftp, "lobby-server/geoip2/GeoLite2-Country.mmdb",
            "netplay-lobby/geoip2/GeoLite2-Country.mmdb")

    with sftp.open("lobby-ui/nick", "w") as fh:
        fh.write(args.nick + "\n")
    with sftp.open("lobby-ui/lobby_ip", "w") as fh:
        fh.write(args.lobby_ip + "\n")
    if args.update_repo:
        with sftp.open("lobby-ui/update_repo", "w") as fh:
            fh.write(args.update_repo.strip() + "\n")

    ssh("mkdir -p /usr/bin && ln -sf /userdata/system/lobby-ui/update.py /usr/bin/lobby-update")
    ssh("chmod 755 /userdata/system/lobby-ui/es_launch.sh "
        "/userdata/system/lobby-ui/lobby_ui.py "
        "/userdata/system/lobby-ui/lobby_watch.py "
        "/userdata/system/lobby-ui/update.py "
        "/userdata/system/lobby-ui/uinput_keys.py "
        "/userdata/system/services/lobby_home "
        "/userdata/system/services/lobby_enter"
        + (" /userdata/system/services/netplay_lobby "
           "/userdata/system/netplay-lobby/netplay-lobby-server-go" if args.lobby_server else ""))

    settings = {
        "global.netplay": "1",
        "global.netplay.nickname": args.nick,
        "global.netplay.port": "55435",
    }
    remote_py = "\n".join([
        "import re",
        "path='/userdata/system/batocera.conf'",
        "add=%r" % settings,
        "lines=open(path).read().splitlines()",
        "out=[]",
        "seen=set()",
        "for ln in lines:",
        "    k=ln.split('=',1)[0]",
        "    if k in add:",
        "        if k in seen: continue",
        "        seen.add(k); out.append(k+'='+add[k])",
        "    else:",
        "        out.append(ln)",
        "for k in add:",
        "    if k not in seen: out.append(k+'='+add[k])",
        "open(path,'w').write('\\n'.join(out)+'\\n')",
    ])
    ssh("python3 - <<'PY'\n" + remote_py + "\nPY")

    for svc in services.split():
        ssh("batocera-services enable %s" % svc)
    if restart_server:
        ssh("batocera-services start netplay_lobby >/dev/null 2>&1 || true")

    with open(os.path.join(HERE, "src/boot-custom.sh"), "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    ssh("mount -o remount,rw /boot && echo '%s' | base64 -d > /boot/boot-custom.sh "
        "&& sync && mount -o remount,ro /boot" % b64)

    info = ssh("grep '^global.netplay' /userdata/system/batocera.conf; "
               "grep '^system.services' /userdata/system/batocera.conf")
    print(info)
    print("done. reboot the target: ssh root@%s reboot" % args.host)

    sftp.close()
    c.close()


if __name__ == "__main__":
    sys.exit(main())
