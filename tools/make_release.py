#!/usr/bin/env python3
"""在本机打包 lobby-ui.tar.gz（GitHub Release 资产）。

产物结构与 update.py 期望的一致：src/ services/ es/ tools/ VERSION README.md
"""
import hashlib
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "dist", "lobby-ui.tar.gz")
INCLUDE = ["src", "services", "es", "tools", "VERSION", "README.md"]
SKIP = {".pyc", ".pyo"}


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tar:
        for rel in INCLUDE:
            path = os.path.join(HERE, rel)
            if not os.path.exists(path):
                print("skip missing", rel)
                continue
            if os.path.isfile(path):
                tar.add(path, arcname=rel)
                continue
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for name in files:
                    if os.path.splitext(name)[1] in SKIP:
                        continue
                    full = os.path.join(root, name)
                    arc = os.path.relpath(full, HERE).replace("\\", "/")
                    tar.add(full, arcname=arc)
    digest = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
    print("wrote", OUT)
    print("sha256", digest)
    print("size", os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
