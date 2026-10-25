#!/usr/bin/env python3
"""打包 easytier-netplay.tar.gz（官方 EasyTier 二进制 + networking/ 脚本）。

用法：make_networking.py <解压后的 easytier-linux-x86_64 目录>
产物：dist/easytier-netplay.tar.gz、dist/easytier.version

update.py 只取 payload/easytier 下的 core/cli 与 VERSION，不改动本机服务配置。
"""
import hashlib
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networking")
OUT = os.path.join(HERE, "dist", "easytier-netplay.tar.gz")
VER_OUT = os.path.join(HERE, "dist", "easytier.version")
PACKAGE_FILES = [
    ("install.sh", 0o755),
    ("uninstall.sh", 0o755),
    ("service-easytier.template", 0o644),
    ("README.md", 0o644),
    ("VERSION", 0o644),
]
BINARIES = ["easytier-core", "easytier-cli"]


def read_version():
    with open(os.path.join(NET, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    bindir = sys.argv[1]
    missing = [n for n in BINARIES if not os.path.isfile(os.path.join(bindir, n))]
    if missing:
        print("missing binaries in %s: %s" % (bindir, ", ".join(missing)))
        return 1

    version = read_version()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(VER_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(version + "\n")

    with tarfile.open(OUT, "w:gz") as tar:
        def add(path, arc, mode):
            info = tar.gettarinfo(path, arcname=arc)
            info.mode = mode
            with open(path, "rb") as fh:
                tar.addfile(info, fh)

        for name, mode in PACKAGE_FILES:
            add(os.path.join(NET, name), name, mode)
        for name in BINARIES:
            add(os.path.join(bindir, name), "payload/easytier/" + name, 0o755)

    digest = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print("wrote", OUT, "version", version)
    print("sha256", digest)
    print("size", os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
