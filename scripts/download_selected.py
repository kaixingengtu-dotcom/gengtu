#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地按需下载脚本：只在你真正需要某个表情包时使用。

用法：
    python scripts/download_selected.py data/2025-01-01.json --output downloads --max 5
    python scripts/download_selected.py data/2025-01-01.json --ids abc123,def456

说明：
    - 默认不下载全部，避免仓库/本地堆积大量图片。
    - 下载的文件只保存在你本地 downloads/ 目录，不会进入 GitHub。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 20


def safe_filename(url: str, fallback: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    if not name or "." not in name:
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        name = f"{fallback or 'emoji'}{ext}"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:120]


def download_one(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download selected emoji images locally")
    parser.add_argument("json_file", type=Path, help="data/YYYY-MM-DD.json")
    parser.add_argument("--output", type=Path, default=Path("downloads"))
    parser.add_argument("--max", type=int, default=5, help="最多下载前 N 条")
    parser.add_argument("--ids", type=str, default="", help="逗号分隔的 id 列表")
    args = parser.parse_args()

    if not args.json_file.exists():
        print(f"file not found: {args.json_file}", file=sys.stderr)
        return 1

    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [it for it in items if it.get("id") in wanted]
    else:
        items = items[: args.max]

    args.output.mkdir(parents=True, exist_ok=True)
    ok = 0
    for it in items:
        url = it.get("image_url") or ""
        if not url:
            print(f"[skip] no image_url: {it.get('id')} {it.get('title', '')}")
            continue
        dest = args.output / safe_filename(url, it.get("id", "emoji"))
        try:
            download_one(url, dest)
            print(f"[ok] {it.get('id')} -> {dest}")
            ok += 1
        except Exception as exc:
            print(f"[fail] {it.get('id')}: {exc}", file=sys.stderr)
    print(f"[done] downloaded {ok}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
