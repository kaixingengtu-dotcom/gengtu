#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 表情雷达本地服务器。

- 提供 docs/ 静态网页
- 提供 /api/search?q=关键词 实时搜索微信公众号表情包文章

启动：
    python server.py
然后打开 http://localhost:8765/
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
PORT = 8765

sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/search":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0] or "").strip()
            self.handle_search(q)
            return
        if parsed.path == "/favicon.ico":
            # 没有图标，直接返回空，避免 404 日志噪音。
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_GET()

    def handle_search(self, q: str) -> None:
        if not q:
            self.send_json({"query": q, "count": 0, "items": [], "error": "empty query"})
            return

        items = []
        # 用原词 + 常见表情包后缀一起搜，提高命中率。
        for query in (q, f"{q} 表情包", f"{q} GIF"):
            items.extend(collect.sogou_weixin_search(query))

        # 去重 + 只保留有图的，避免网页出现空白卡片。
        seen = set()
        result = []
        for item in items:
            key = item.page_url or item.title
            if key in seen:
                continue
            seen.add(key)
            if item.image_url:
                result.append(item.to_dict())

        result.sort(key=lambda x: -float(x.get("score") or 0))
        self.send_json({"query": q, "count": len(result), "items": result[:60]})

    def send_json(self, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("[server] " + fmt % args + "\n")


if __name__ == "__main__":
    print("DeepSeek 表情雷达本地服务器启动：http://localhost:%d" % PORT)
    print("老梗搜索：http://localhost:%d/search.html" % PORT)
    print("按 Ctrl+C 停止")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
