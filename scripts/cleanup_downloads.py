#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地清理脚本：删除 downloads/ 里超过 N 天的图片，避免占空间。

用法：
    python scripts/cleanup_downloads.py --days 30
    python scripts/cleanup_downloads.py --days 7 --downloads downloads
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean old downloaded emoji images")
    parser.add_argument("--downloads", type=Path, default=Path("downloads"))
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    if not args.downloads.exists():
        print(f"目录不存在，无需清理：{args.downloads}")
        return 0

    cutoff = time.time() - args.days * 86400
    removed = 0
    for f in args.downloads.rglob("*"):
        if f.is_file():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
                    print(f"[del] {f}")
            except OSError as exc:
                print(f"[skip] {f}: {exc}")

    # 删除清理后变空的子目录
    for d in sorted(args.downloads.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
                print(f"[rmdir] {d}")
            except OSError:
                pass

    print(f"[done] removed {removed} files older than {args.days} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
