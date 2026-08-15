#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日中文热门表情包采集器（仅标准库，无 AI，无付费 API）。

设计目标：
- 费用尽量低：不调用任何 LLM/视觉 API，不下载原图入库，只保存外链与元数据。
- 数据源为“最佳努力”模式：某个源挂了不影响其他源。
- 输出：
    data/YYYY-MM-DD.json   结构化结果
    docs/YYYY-MM-DD.md     人类可读日报，图片使用远程外链预览
    docs/index.md          最近日报索引
- 本地可按需执行 scripts/download_selected.py 下载真正需要的图片。

用法：
    python scripts/collect.py [--top 30] [--keep-days 30]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 12
MAX_PER_SOURCE = 40
DEFAULT_TOP = 30
DEFAULT_KEEP_DAYS = 30
DEFAULT_SOURCES = "weibo,fabiaoqing,doutu,tieba,dbbqb"

# 用于识别真正的图片链接，过滤掉图标/占位图。
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)(?:\?|#|$)", re.I)

# 部分表情包站点证书过期/链不完整；只读抓取时忽略证书错误以提高成功率。
SSL_CONTEXT = ssl._create_unverified_context()


@dataclass
class EmojiItem:
    id: str
    title: str
    source: str
    page_url: str
    image_url: str
    score: float = 0.0
    published_at: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def http_get(url: str, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def http_get_text(url: str, timeout: int = TIMEOUT) -> str:
    raw = http_get(url, timeout=timeout)
    # 优先按响应头 charset 解码，失败则尝试 UTF-8。
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("gbk", errors="replace")


def http_get_json(url: str, timeout: int = TIMEOUT) -> dict | list:
    raw = http_get(url, timeout=timeout)
    return json.loads(raw.decode("utf-8", errors="replace"))


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def first_attr(tag: str, names: tuple[str, ...]) -> str:
    """从 HTML tag 字符串中取第一个存在的属性值。"""
    for name in names:
        m = re.search(
            rf'{name}\s*=\s*["\']([^"\']*)["\']', tag, flags=re.I
        )
        if m:
            return m.group(1).strip()
    return ""


def make_id(source: str, *parts: str) -> str:
    raw = "|".join([source] + [p for p in parts if p])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_image_url(url: str, base_url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    if url.startswith(("http://", "https://")):
        return url
    return ""


def looks_like_image(url: str) -> bool:
    return bool(url) and bool(IMAGE_EXT_RE.search(url))


def human_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


# --------------------------------------------------------------------------- #
# 数据源：每个函数返回 list[EmojiItem]，内部自行容错
# --------------------------------------------------------------------------- #

def fetch_weibo() -> list[EmojiItem]:
    """微博搜索“表情包”，综合+最新各取一次，按互动量给热度分。"""
    items: list[EmojiItem] = []
    # 100103type=1 是微博搜索容器；sort=time 尽量拿新内容，失败就忽略。
    for sort in (None, "time"):
        params = {"containerid": "100103type=1&q=表情包", "page_type": "searchall"}
        if sort:
            params["sort"] = sort
        url = "https://m.weibo.cn/api/container/getIndex?" + urllib.parse.urlencode(params)
        try:
            data = http_get_json(url)
        except Exception as exc:
            print(f"[weibo] {sort or 'hot'} request failed: {exc}", file=sys.stderr)
            continue

        cards = ((data or {}).get("data") or {}).get("cards") or []
        for card in cards:
            mblog = card.get("mblog") or {}
            if not mblog:
                continue
            pics = mblog.get("pics") or []
            if not pics:
                continue
            img = ""
            for pic in pics:
                large = pic.get("large") or {}
                img = large.get("url") or pic.get("url") or ""
                if img:
                    break
            if not img:
                continue
            mid = mblog.get("idstr") or mblog.get("id") or ""
            if not mid:
                continue
            title = clean_html(mblog.get("text", ""))[:80] or "微博表情包"
            score = (
                int(mblog.get("reposts_count") or 0)
                + 2 * int(mblog.get("comments_count") or 0)
                + int(mblog.get("attitudes_count") or 0)
            )
            items.append(
                EmojiItem(
                    id=make_id("weibo", mid),
                    title=title,
                    source="微博",
                    page_url=f"https://m.weibo.cn/status/{mid}",
                    image_url=img,
                    score=float(score),
                    published_at=mblog.get("created_at", ""),
                )
            )
    return items


def fetch_fabiaoqing() -> list[EmojiItem]:
    """发表情网热门列表页，解析图片外链。"""
    items: list[EmojiItem] = []
    for page in (1, 2):
        url = f"https://www.fabiaoqing.com/biaoqing/lists/page/{page}.html"
        try:
            text = http_get_text(url)
        except Exception as exc:
            print(f"[fabiaoqing] page {page} failed: {exc}", file=sys.stderr)
            continue

        # 发表情页面的表情图通常是 <img ... data-original="..." alt="...">
        for m in re.finditer(r"<img[^>]+>", text, flags=re.I):
            tag = m.group(0)
            img = normalize_image_url(
                first_attr(tag, ("data-original", "data-src", "src")), url
            )
            if not looks_like_image(img):
                continue
            title = clean_html(first_attr(tag, ("alt", "title"))) or "发表情表情包"
            items.append(
                EmojiItem(
                    id=make_id("fabiaoqing", img),
                    title=title[:80],
                    source="发表情",
                    page_url=url,
                    image_url=img,
                    score=10.0,
                    published_at="",
                )
            )
    return items[:MAX_PER_SOURCE]


def fetch_doutu() -> list[EmojiItem]:
    """斗图啦文章/图片列表，尽量解析图片外链。"""
    items: list[EmojiItem] = []
    urls = [
        "https://www.doutula.com/article/list/?page=1",
        "https://www.doutula.com/photo/list/?page=1",
    ]
    for url in urls:
        try:
            text = http_get_text(url)
        except Exception as exc:
            print(f"[doutu] {url} failed: {exc}", file=sys.stderr)
            continue

        for m in re.finditer(r"<img[^>]+>", text, flags=re.I):
            tag = m.group(0)
            img = normalize_image_url(
                first_attr(tag, ("data-original", "data-src", "src")), url
            )
            if not looks_like_image(img):
                continue
            title = clean_html(first_attr(tag, ("alt", "title"))) or "斗图啦表情包"
            items.append(
                EmojiItem(
                    id=make_id("doutu", img),
                    title=title[:80],
                    source="斗图啦",
                    page_url=url,
                    image_url=img,
                    score=8.0,
                    published_at="",
                )
            )
    return items[:MAX_PER_SOURCE]


def fetch_tieba() -> list[EmojiItem]:
    """贴吧“表情包”吧热门/最新帖，尽量取封面图。"""
    items: list[EmojiItem] = []
    url = "https://tieba.baidu.com/f?kw=" + urllib.parse.quote("表情包") + "&ie=utf-8"
    try:
        text = http_get_text(url)
    except Exception as exc:
        print(f"[tieba] request failed: {exc}", file=sys.stderr)
        return items

    # 贴吧帖子标题：<a ... href="/p/123" title="标题" ...>
    thread_re = re.compile(
        r'<a[^>]+href=["\'](/p/\d+)["\'][^>]*title=["\']([^"\']*)["\']',
        flags=re.I,
    )
    for href, title in thread_re.findall(text):
        title = clean_html(title)
        if not title:
            continue
        page_url = "https://tieba.baidu.com" + href
        items.append(
            EmojiItem(
                id=make_id("tieba", href),
                title=title[:80],
                source="贴吧",
                page_url=page_url,
                image_url="",  # 封面图解析不稳定；下载脚本会跳过无图项
                score=6.0,
                published_at="",
            )
        )
    return items[:MAX_PER_SOURCE]


def fetch_dbbqb() -> list[EmojiItem]:
    """逗逼表情包公开搜索接口（尽力而为，失败不影响其他源）。"""
    items: list[EmojiItem] = []
    url = "https://www.dbbqb.com/api/search/json?size=30&start=0"
    try:
        data = http_get_json(url)
    except Exception as exc:
        print(f"[dbbqb] request failed: {exc}", file=sys.stderr)
        return items

    if not isinstance(data, list):
        return items

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        img = item.get("path") or item.get("url") or item.get("image") or ""
        img = normalize_image_url(img, "https://www.dbbqb.com")
        if not looks_like_image(img):
            continue
        title = item.get("name") or item.get("title") or "逗逼表情包"
        items.append(
            EmojiItem(
                id=make_id("dbbqb", img),
                title=str(title)[:80],
                source="逗逼表情包",
                page_url=url,
                image_url=img,
                score=5.0,
                published_at="",
            )
        )
    return items


def fetch_reddit() -> list[EmojiItem]:
    """Reddit r/memes 热门（可选兜底源，默认不启用）。"""
    items: list[EmojiItem] = []
    url = "https://www.reddit.com/r/memes/hot.json?limit=25&raw_json=1"
    try:
        data = http_get_json(url)
    except Exception as exc:
        print(f"[reddit] request failed: {exc}", file=sys.stderr)
        return items

    children = ((data or {}).get("data") or {}).get("children") or []
    for child in children:
        post = child.get("data") or {}
        if post.get("stickied") or post.get("over_18"):
            continue
        image_url = post.get("url") or ""
        if not looks_like_image(image_url):
            preview = post.get("preview") or {}
            images = preview.get("images") or []
            if images:
                image_url = (images[0].get("source") or {}).get("url") or ""
                image_url = image_url.replace("&amp;", "&")
        if not image_url:
            continue
        post_id = post.get("id") or ""
        permalink = post.get("permalink") or ""
        created = ""
        try:
            created = datetime.fromtimestamp(
                post.get("created_utc") or 0, tz=timezone.utc
            ).isoformat(timespec="seconds")
        except Exception:
            pass
        items.append(
            EmojiItem(
                id=make_id("reddit", post_id),
                title=(post.get("title") or "Reddit meme")[:80],
                source="Reddit",
                page_url="https://www.reddit.com" + permalink,
                image_url=image_url,
                score=float(post.get("ups") or 0),
                published_at=created,
            )
        )
    return items


SOURCES = {
    "weibo": fetch_weibo,
    "fabiaoqing": fetch_fabiaoqing,
    "doutu": fetch_doutu,
    "tieba": fetch_tieba,
    "dbbqb": fetch_dbbqb,
    "reddit": fetch_reddit,
}


# --------------------------------------------------------------------------- #
# 合并、排序、输出
# --------------------------------------------------------------------------- #

def merge_items(all_items: list[EmojiItem]) -> list[EmojiItem]:
    merged: dict[str, EmojiItem] = {}
    for item in all_items:
        key = item.id
        # 兜底：相同图片 URL 也视为同一表情。
        if item.image_url:
            key = make_id("img", item.image_url)
        old = merged.get(key)
        if old is None:
            merged[key] = item
        else:
            # 保留分数更高、标题更完整、有图的一项。
            if item.score > old.score:
                old.score = item.score
            if not old.title or old.title.endswith("表情包"):
                old.title = item.title or old.title
            if not old.page_url and item.page_url:
                old.page_url = item.page_url
            if old.tags and item.source not in old.tags:
                old.tags.append(item.source)
    return sorted(merged.values(), key=lambda x: (x.score, x.image_url), reverse=True)


def write_json(path: Path, items: list[EmojiItem], generated_at: str) -> None:
    payload = {
        "generated_at": generated_at,
        "date": date.today().isoformat(),
        "count": len(items),
        "items": [i.to_dict() for i in items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, items: list[EmojiItem], generated_at: str) -> None:
    today = date.today().isoformat()
    lines = [
        f"# 每日热门表情包 {today}",
        "",
        f"> 自动生成于 {human_time(generated_at)}。仅收录外链，不下载原图；使用请注意来源与版权。",
        "",
        f"共 {len(items)} 条。",
        "",
    ]
    for idx, item in enumerate(items, 1):
        lines.append(f"## {idx}. {item.title}")
        lines.append("")
        lines.append(f"- 来源：{item.source}")
        lines.append(f"- 热度分：{item.score:.0f}")
        if item.published_at:
            lines.append(f"- 时间：{item.published_at}")
        lines.append(f"- 原图：{item.image_url}")
        lines.append(f"- 页面：{item.page_url}")
        lines.append("")
        if item.image_url:
            lines.append(f"![{item.title}]({item.image_url})")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_index(docs_dir: Path, days: list[str]) -> None:
    lines = [
        "# 表情包日报索引",
        "",
        "每日自动生成。最新在最上面。",
        "",
    ]
    for d in days:
        lines.append(f"- [{d}]({d}.md)")
    lines.append("")
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _card_html(item: EmojiItem, idx: int) -> str:
    title = html.escape(item.title or "表情包", quote=True)
    source = html.escape(item.source, quote=True)
    page = html.escape(item.page_url or "#", quote=True)
    img = html.escape(item.image_url, quote=True)
    score = f"{item.score:.0f}"
    pub = html.escape(item.published_at, quote=True)

    if item.image_url:
        media = (
            f'<a href="{page}" target="_blank" rel="noopener">'
            f'<img src="{img}" alt="{title}" loading="lazy" '
            f'onerror="this.parentNode.classList.add(\'broken\')"></a>'
        )
    else:
        media = (
            f'<div class="no-image"><a href="{page}" target="_blank" rel="noopener">'
            f"暂无图片，点此看来源</a></div>"
        )

    return f"""<div class="card">
  {media}
  <div class="info">
    <div class="title">{title}</div>
    <div class="meta">{source} · 热度 {score}{f" · {pub}" if pub else ""}</div>
    <a class="page-link" href="{page}" target="_blank" rel="noopener">查看来源</a>
  </div>
</div>"""


def write_html(path: Path, items: list[EmojiItem], generated_at: str) -> None:
    today = date.today().isoformat()
    cards = "\n".join(_card_html(item, i) for i, item in enumerate(items, 1))
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日热门表情包 {today}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f7; color: #222; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px 16px 60px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
  .card {{ background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; flex-direction: column; }}
  .card a img {{ width: 100%; height: 200px; object-fit: cover; display: block; background: #eee; }}
  .card .broken a {{ display: block; width: 100%; height: 200px; background: #eee; }}
  .no-image {{ height: 200px; display: flex; align-items: center; justify-content: center; background: #eee; color: #666; font-size: 13px; }}
  .no-image a {{ color: #1677ff; text-decoration: none; }}
  .info {{ padding: 10px 12px 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }}
  .title {{ font-size: 14px; font-weight: 600; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .meta {{ color: #888; font-size: 12px; }}
  .page-link {{ color: #1677ff; font-size: 13px; text-decoration: none; margin-top: auto; }}
  .back {{ display: inline-block; margin-bottom: 16px; color: #1677ff; text-decoration: none; font-size: 14px; }}
</style>
</head>
<body>
<div class="container">
  <a class="back" href="index.html">← 返回日报索引</a>
  <h1>每日热门表情包 {today}</h1>
  <div class="sub">自动生成于 {human_time(generated_at)} · 共 {len(items)} 条 · 仅收录外链，使用请注意来源与版权</div>
  <div class="grid">
{cards}
  </div>
</div>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")


def write_index_html(docs_dir: Path, days: list[str]) -> None:
    links = "\n".join(
        f'    <li><a href="{d}.html">{d}</a></li>' for d in days
    )
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>表情包日报索引</title>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f7; color: #222; }}
  .container {{ max-width: 720px; margin: 0 auto; padding: 30px 16px; }}
  h1 {{ font-size: 26px; }}
  p {{ color: #666; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ margin: 10px 0; }}
  a {{ color: #1677ff; text-decoration: none; font-size: 16px; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="container">
  <h1>😀 表情包日报索引</h1>
  <p>每日自动生成，点日期打开当天的表情墙。</p>
  <ul>
{links}
  </ul>
</div>
</body>
</html>
"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.html").write_text(html_doc, encoding="utf-8")


def prune_old(data_dir: Path, docs_dir: Path, keep_days: int) -> None:
    cutoff = date.today() - timedelta(days=keep_days)
    for d in list(data_dir.glob("????-??-??.json")):
        try:
            fdate = date.fromisoformat(d.stem)
        except ValueError:
            continue
        if fdate < cutoff:
            d.unlink(missing_ok=True)
            for suffix in (".md", ".html"):
                (docs_dir / f"{d.stem}{suffix}").unlink(missing_ok=True)
            print(f"[prune] removed {d.stem}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Chinese hot emoji collector")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument(
        "--sources",
        default=DEFAULT_SOURCES,
        help="逗号分隔的数据源，默认仅中文源；需要外网兜底可加 reddit",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    docs_dir = Path(args.docs_dir)
    top = max(1, min(args.top, 100))
    keep_days = max(1, args.keep_days)

    selected_sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    all_items: list[EmojiItem] = []
    for name in selected_sources:
        fn = SOURCES.get(name)
        if not fn:
            print(f"[skip] unknown source: {name}", file=sys.stderr)
            continue
        print(f"[fetch] {name} ...")
        try:
            items = fn()
        except Exception as exc:
            print(f"[error] {name}: {exc}", file=sys.stderr)
            items = []
        print(f"[fetch] {name}: {len(items)} items")
        all_items.extend(items)

    merged = merge_items(all_items)
    merged = merged[:top]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    today = date.today().isoformat()
    json_path = output_dir / f"{today}.json"
    md_path = docs_dir / f"{today}.md"
    html_path = docs_dir / f"{today}.html"

    write_json(json_path, merged, generated_at)
    write_markdown(md_path, merged, generated_at)
    write_html(html_path, merged, generated_at)

    # 重建索引：最新日期排前面。
    all_days = sorted(
        (p.stem for p in output_dir.glob("????-??-??.json") if p.stem <= today),
        reverse=True,
    )
    write_index(docs_dir, all_days[:30])
    write_index_html(docs_dir, all_days[:30])
    prune_old(output_dir, docs_dir, keep_days)

    print(f"[done] {len(merged)} items -> {json_path} / {md_path} / {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
