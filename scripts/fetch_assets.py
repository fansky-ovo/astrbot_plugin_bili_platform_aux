# -*- coding: utf-8 -*-
"""把可选资源（彩色 emoji 字体、左上角头像）放到插件的持久资源目录。

用法（在服务器上执行）：

    python scripts/fetch_assets.py                     # 只取 emoji 字体
    python scripts/fetch_assets.py --avatar /path/avatar.png
    python scripts/fetch_assets.py --data-dir /root/astrbot/data/bili_platform_aux

emoji 字体是**可选**的：没有它渲染时会把 emoji 去掉，而不是画出豆腐块。
脚本优先用 `apt-get download fonts-noto-color-emoji`（Debian/Ubuntu），
失败再尝试 HTTP 镜像。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HTTP_MIRRORS = [
    "https://cdn.jsdelivr.net/gh/googlefonts/noto-emoji@main/fonts/NotoColorEmoji.ttf",
    "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/NotoColorEmoji.ttf",
]


def _download(url: str, target: pathlib.Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    except Exception as exc:
        print(f"  下载失败 {url}: {type(exc).__name__} {exc}")
        return False
    if len(data) < 100_000:
        print(f"  内容过小，跳过 {url}")
        return False
    target.write_bytes(data)
    return True


def _from_apt(target: pathlib.Path) -> bool:
    if not shutil.which("apt-get") or not shutil.which("dpkg-deb"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                ["apt-get", "download", "fonts-noto-color-emoji"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
        except Exception as exc:
            print(f"  apt-get download 失败: {type(exc).__name__}")
            return False
        debs = sorted(pathlib.Path(tmp).glob("*.deb"))
        if not debs:
            return False
        extract = pathlib.Path(tmp) / "x"
        try:
            subprocess.run(
                ["dpkg-deb", "-x", str(debs[0]), str(extract)],
                check=True,
                capture_output=True,
            )
        except Exception as exc:
            print(f"  dpkg-deb 失败: {type(exc).__name__}")
            return False
        found = sorted(extract.rglob("NotoColorEmoji.ttf"))
        if not found:
            return False
        shutil.copyfile(found[0], target)
        return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--avatar", default="", help="左上角头像图片（可选）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    data_dir = pathlib.Path(
        args.data_dir
        or os.environ.get("BILI_PLATFORM_AUX_DATA_DIR", "data/bili_platform_aux")
    )
    resources = data_dir / "resources"
    resources.mkdir(parents=True, exist_ok=True)

    emoji = resources / "NotoColorEmoji.ttf"
    if emoji.exists() and not args.force:
        print(f"emoji 字体已存在: {emoji} ({emoji.stat().st_size} bytes)")
    else:
        print("获取彩色 emoji 字体 ...")
        ok = _from_apt(emoji)
        if not ok:
            for url in HTTP_MIRRORS:
                print(f"  尝试 {url}")
                if _download(url, emoji):
                    ok = True
                    break
        if ok:
            print(f"已写入 {emoji} ({emoji.stat().st_size} bytes)")
        else:
            print("未取到 emoji 字体；渲染时会自动去掉 emoji（不影响发布）")

    if args.avatar:
        source = pathlib.Path(args.avatar).expanduser()
        target = resources / "avatar.png"
        if source.is_file():
            shutil.copyfile(source, target)
            print(f"左上角头像已写入 {target}")
        else:
            print(f"头像来源不存在: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
