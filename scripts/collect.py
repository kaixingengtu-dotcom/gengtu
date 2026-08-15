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
MAX_PER_SOURCE = 120
DEFAULT_TOP = 60
DEFAULT_KEEP_DAYS = 180
DEFAULT_MAX_AGE_DAYS = 0
DEFAULT_SOURCES = "sogou_weixin"

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


def sogou_thumb_to_original(thumb_url: str) -> str:
    """把搜狗缩略图地址转成微信原图地址（mmbiz.qpic.cn），避免防盗链加载失败。"""
    if "sogoucdn.com/v2/thumb" not in thumb_url:
        return thumb_url
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(thumb_url).query)
    orig = qs.get("url", [""])[0]
    if not orig:
        return thumb_url
    if orig.startswith("http://"):
        orig = "https://" + orig[len("http://"):]
    return orig


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
            # 跳过占位图/图标/横幅，只保留真实表情图。
            if not looks_like_image(img):
                continue
            if "static.doutupk.com" in img or "loader.gif" in img or "/img/gif.png" in img:
                continue
            # 斗图啦的标题/日期在图片前面的 random_title 区块里。
            title = "斗图啦表情包"
            published_at = ""
            before = text[: m.start()]
            title_matches = list(
                re.finditer(
                    r'<div class="random_title">(.*?)<div class="date">([^<]+)</div>',
                    before,
                    flags=re.S,
                )
            )
            if title_matches:
                title = clean_html(title_matches[-1].group(1)) or title
                published_at = clean_html(title_matches[-1].group(2))
            else:
                title_matches = list(
                    re.finditer(
                        r'<div class="random_title">([^<]+)</div>',
                        before,
                        flags=re.S,
                    )
                )
                if title_matches:
                    title = clean_html(title_matches[-1].group(1)) or title
            items.append(
                EmojiItem(
                    id=make_id("doutu", img),
                    title=title[:80],
                    source="斗图啦",
                    page_url=url,
                    image_url=img,
                    score=8.0,
                    published_at=published_at,
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


def fetch_reddit_subreddit(subreddit: str) -> list[EmojiItem]:
    """Reddit 某个 subreddit 的 hot 帖。"""
    items: list[EmojiItem] = []
    url = (
        f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25&raw_json=1"
    )
    try:
        data = http_get_json(url)
    except Exception as exc:
        print(f"[reddit/{subreddit}] request failed: {exc}", file=sys.stderr)
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
                id=make_id(f"reddit-{subreddit}", post_id),
                title=(post.get("title") or f"{subreddit} meme")[:80],
                source=f"Reddit/{subreddit}",
                page_url="https://www.reddit.com" + permalink,
                image_url=image_url,
                score=float(post.get("ups") or 0),
                published_at=created,
            )
        )
    return items


def fetch_reddit() -> list[EmojiItem]:
    """Reddit r/memes 热门（通用兜底源）。"""
    return fetch_reddit_subreddit("memes")


def fetch_reddit_anime() -> list[EmojiItem]:
    """二次元梗图：多个动漫 meme 版块，合并取热门前排。"""
    items: list[EmojiItem] = []
    for subreddit in ("Animemes", "goodanimemes", "AnimeFunny", "AnimeMeme"):
        items.extend(fetch_reddit_subreddit(subreddit))
    return items


def sogou_weixin_search(query: str) -> list[EmojiItem]:
    """按单个关键词实时搜索微信公众号文章（搜狗微信）。"""
    items: list[EmojiItem] = []
    url = (
        "https://weixin.sogou.com/weixin?type=2&query="
        + urllib.parse.quote(query)
    )
    try:
        text = http_get_text(url)
    except Exception as exc:
        print(f"[sogou_weixin] query {query!r} failed: {exc}", file=sys.stderr)
        return items

    # 搜狗微信文章搜索结果一般是一个个 .txt-box 块。
    blocks = re.split(r'<div class="txt-box">', text)[1:]
    for pos, block in enumerate(blocks):
        block = block.split('<div class="txt-box">')[0]
        title_m = re.search(
            r"<h3>\s*<a[^>]*>(.*?)</a>", block, flags=re.S | re.I
        )
        if not title_m:
            continue
        title = clean_html(title_m.group(1))[:80]
        link_m = re.search(
            r'<a[^>]*href="([^"]+)"', block, flags=re.I
        )
        page_url = ""
        if link_m:
            page_url = urllib.parse.urljoin(url, html.unescape(link_m.group(1)))
        # 优先取搜狗缩略图或微信公众号原图，避免抓到图标/占位图。
        image_url = ""
        all_imgs = re.findall(
            r'<img[^>]+(?:src|data-src)="([^"]+)"', block, flags=re.I
        )
        for raw in all_imgs:
            candidate = normalize_image_url(raw, url)
            if "sogoucdn.com" in candidate or "mmbiz.qpic.cn" in candidate:
                image_url = sogou_thumb_to_original(candidate)
                break
        if not image_url and all_imgs:
            image_url = sogou_thumb_to_original(
                normalize_image_url(all_imgs[0], url)
            )
        account_m = re.search(
            r'class="all-time-y2">([^<]+)</span>', block, flags=re.I
        )
        account = clean_html(account_m.group(1)) if account_m else "微信公众号"
        date_m = re.search(
            r"timeConvert\('(\d+)'\)", block, flags=re.I
        )
        published_at = ""
        if date_m:
            try:
                published_at = datetime.fromtimestamp(
                    int(date_m.group(1)), tz=timezone.utc
                ).isoformat(timespec="seconds")
            except Exception:
                published_at = ""
        items.append(
            EmojiItem(
                id=make_id("sogou_weixin", page_url or title),
                title=f"[公众号] {title}",
                source=f"微信/{account}",
                page_url=page_url,
                image_url=image_url,
                score=float(max(0, 10 - pos)),
                published_at=published_at,
            )
        )
    return items


def fetch_sogou_weixin() -> list[EmojiItem]:
    """搜狗微信搜索：用多组关键词批量找公众号发的表情包文章。"""
    items: list[EmojiItem] = []
    title_counter: dict[str, int] = {}
    best_position: dict[str, int] = {}
    queries = (
        "表情包 GIF",
        "二次元 表情包",
        "热门表情包",
        "可爱表情包",
        "沙雕表情包",
        "微信表情包",
        "动态表情包",
        "搞笑表情包",
        "动漫表情包",
        "情侣表情包",
    )
    for query in queries:
        q_items = sogou_weixin_search(query)
        for pos, item in enumerate(q_items):
            title_key = re.sub(r"\s+", "", item.title.replace("[公众号] ", ""))
            title_counter[title_key] = title_counter.get(title_key, 0) + 1
            best_position[title_key] = min(
                best_position.get(title_key, 999), pos
            )
        items.extend(q_items)

    # 综合热度分：同一标题被多个关键词搜到 + 新近度加成。
    now_ts = datetime.now(timezone.utc).timestamp()
    for item in items:
        title_key = re.sub(r"\s+", "", item.title.replace("[公众号] ", ""))
        hits = title_counter.get(title_key, 1)
        best_pos = best_position.get(title_key, 99)
        position_bonus = max(0.0, 10.0 - 2.0 * best_pos)
        item.score = 10.0 + 5.0 * (hits - 1) + position_bonus
        try:
            ts = datetime.fromisoformat(
                item.published_at.replace("Z", "+00:00")
            ).timestamp()
            age_days = (now_ts - ts) / 86400
            if age_days <= 7:
                item.score += 10.0
            elif age_days <= 30:
                item.score += 5.0
        except Exception:
            pass

    return items[:MAX_PER_SOURCE]


SOURCES = {
    "weibo": fetch_weibo,
    "fabiaoqing": fetch_fabiaoqing,
    "doutu": fetch_doutu,
    "tieba": fetch_tieba,
    "dbbqb": fetch_dbbqb,
    "reddit": fetch_reddit,
    "reddit_anime": fetch_reddit_anime,
    "sogou_weixin": fetch_sogou_weixin,
}


# --------------------------------------------------------------------------- #
# 合并、排序、输出
# --------------------------------------------------------------------------- #

def _date_sort_key(item: EmojiItem) -> float:
    """尽量把有日期的、更新的排前面；解析失败按 0 处理。"""
    s = (item.published_at or "").strip()
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").timestamp()
    except Exception:
        return 0.0


def _source_priority(item: EmojiItem) -> int:
    """排序优先级：微信公众号最优先，Reddit 二次元其次，其他最后。"""
    if item.source.startswith("微信"):
        return 0
    if "Reddit" in item.source:
        return 1
    return 2


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
    return sorted(
        merged.values(),
        key=lambda x: (
            _source_priority(x),
            -x.score,
            -_date_sort_key(x),
            x.image_url,
        ),
    )


GENERIC_THEME_WORDS = {
    "表情包", "动态", "图片", "热门", "可爱", "合集", "大全", "推荐",
    "最新", "分享", "聊天", "专用", "必备", "系列", "第二", "第三",
    "第", "张", "款", "个", "种", "用", "了", "的", "和", "吧",
    "啊", "吗", "gif", "GIF", "微信", "公众号", "今天", "今日", "早安", "晚安",
    # 常见泛化品类/形容词，不是具体梗名
    "情侣", "搞笑", "卡通", "沙雕", "抽象", "日常", "治愈", "温柔",
    "高级", "简约", "唯美", "伤感", "贱", "萌", "甜", "酷", "帅", "美",
    "壁纸", "头像", "文案", "背景", "素材", "表情", "动图", "图片",
    "动漫", "有趣", "好玩", "好看", "魔性", "上头", "洗脑", "可爱",
}


def detect_hot_themes(
    items: list[EmojiItem],
    min_count: int = 2,
    min_accounts: int = 2,
    max_themes: int = 5,
) -> list[dict]:
    """从当天标题里找出被多个公众号反复引用的梗名（如“草地牛”）。

    纯规则实现，不调用 AI：
    1. 先从“xxx表情包/动图/gif/合集”和引号里提取候选梗名。
    2. 再统计这些候选名在当天所有标题里被多少篇文章、多少个公众号提到。
    3. 这样“草地牛表情包”和“草地牛又火了”都能被算到同一个梗名。
    """
    def clean_title(title: str) -> str:
        s = re.sub(r"\[公众号\]", "", title or "")
        s = re.sub(
            r"[【】\[\]()（）:：,，。！!?？\"'“”·|丨\s\d._-]+", "", s
        )
        return s

    def is_valid_name(name: str) -> bool:
        name = name.strip()
        if len(name) < 2:
            return False
        if name.lower() in GENERIC_THEME_WORDS:
            return False
        if not re.search(r"[\u4e00-\u9fa5A-Za-z]", name):
            return False
        return True

    pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})"
        r"(?:表情包|动图|gif|GIF|图片|合集|动态|系列|推荐|大全)"
    )
    quote_pattern = re.compile(
        r'[“"「『]([\u4e00-\u9fa5A-Za-z0-9]{2,12})[”"」』]'
    )

    candidate_names: set[str] = set()

    for item in items:
        title = clean_title(item.title)
        for m in pattern.finditer(title):
            name = m.group(1)
            for word in sorted(GENERIC_THEME_WORDS, key=len, reverse=True):
                if name.endswith(word):
                    name = name[: -len(word)]
                    break
                if name.startswith(word):
                    name = name[len(word):]
                    break
            if is_valid_name(name):
                candidate_names.add(name)

        for m in quote_pattern.finditer(item.title or ""):
            name = m.group(1)
            if is_valid_name(name):
                candidate_names.add(name)

    # 统计每个候选梗名在多少篇文章/多少个公众号里出现，并记录一张代表图。
    name_count: dict[str, int] = {}
    name_accounts: dict[str, set[str]] = {}
    name_image: dict[str, str] = {}
    name_page: dict[str, str] = {}
    for item in items:
        account = item.source.split("/", 1)[-1] if "/" in item.source else item.source
        title = clean_title(item.title)
        for name in candidate_names:
            if name in title:
                name_count[name] = name_count.get(name, 0) + 1
                name_accounts.setdefault(name, set()).add(account)
                if name not in name_image and item.image_url:
                    name_image[name] = item.image_url
                    name_page[name] = item.page_url

    themes = []
    for name, cnt in name_count.items():
        if cnt >= min_count and len(name_accounts[name]) >= min_accounts:
            themes.append(
                {
                    "name": name,
                    "count": cnt,
                    "accounts": len(name_accounts[name]),
                    "image": name_image.get(name, ""),
                    "page": name_page.get(name, ""),
                }
            )

    # 长的、出现多的优先；子串被更长且不更少的主题覆盖时丢弃。
    themes.sort(
        key=lambda x: (-x["count"], -x["accounts"], -len(x["name"]), x["name"])
    )
    accepted: list[dict] = []
    for theme in themes:
        is_sub = False
        for old in accepted:
            if (
                theme["name"] in old["name"]
                and theme["count"] <= old["count"]
                and theme["accounts"] <= old["accounts"]
            ):
                is_sub = True
                break
        if not is_sub:
            accepted.append(theme)
        if len(accepted) >= max_themes:
            break

    return accepted[:max_themes]


def build_summary(items: list[EmojiItem]) -> dict:
    """生成今日总结/推荐（规则版，不调用 AI）。"""
    if not items:
        return {"text": "今日暂无表情包。", "top": [], "themes": []}

    top = items[:3]
    account_counter: dict[str, int] = {}
    for item in items:
        acct = item.source.split("/", 1)[-1] if "/" in item.source else item.source
        account_counter[acct] = account_counter.get(acct, 0) + 1
    top_accounts = sorted(
        account_counter.items(), key=lambda x: (-x[1], x[0])
    )[:3]
    accounts_text = "、".join(f"{name}({cnt}条)" for name, cnt in top_accounts)
    top_text = "；".join(
        f"「{item.title.replace('[公众号] ', '')[:25]}」热度{item.score:.0f}"
        for item in top
    )
    themes = detect_hot_themes(items, min_count=2, min_accounts=2, max_themes=5)
    themes_text = "、".join(f"{t['name']}({t['count']}篇)" for t in themes)
    text = (
        f"今日共 {len(items)} 条热门表情包，全部来自微信公众号。"
        f"推荐先看：{top_text}。"
        f"今日出现较多的公众号：{accounts_text}。"
    )
    if themes_text:
        text += f"今日热门梗：{themes_text}。"
    else:
        text += "今日热门梗：暂无明显重复梗。"
    return {
        "text": text,
        "top": [item.to_dict() for item in top],
        "themes": themes,
    }


def write_json(path: Path, items: list[EmojiItem], generated_at: str) -> None:
    payload = {
        "generated_at": generated_at,
        "date": date.today().isoformat(),
        "count": len(items),
        "summary": build_summary(items),
        "items": [i.to_dict() for i in items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, items: list[EmojiItem], generated_at: str) -> None:
    today = date.today().isoformat()
    summary = build_summary(items)
    lines = [
        f"# 每日热门表情包 {today}",
        "",
        f"> 自动生成于 {human_time(generated_at)}。仅收录外链，不下载原图；使用请注意来源与版权。",
        "",
        f"共 {len(items)} 条。",
        "",
        "## 📌 今日推荐",
        "",
        summary["text"],
        "",
    ]
    if summary["top"]:
        lines.append("### 最热 Top 3")
        lines.append("")
        for rank, item in enumerate(summary["top"], 1):
            title = item.get("title", "")
            page = item.get("page_url", "")
            score = item.get("score", 0)
            lines.append(f"{rank}. [{title}]({page})（热度 {score:.0f}）")
        lines.append("")
    lines.append("### 🔥 今日热门梗")
    lines.append("")
    if summary.get("themes"):
        for theme in summary["themes"]:
            lines.append(
                f"- {theme['name']}：{theme['count']} 篇，{theme['accounts']} 个公众号提到"
            )
    else:
        lines.append("- 暂无明显重复梗。")
    lines.append("")
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


def _dict_to_item(data: dict) -> EmojiItem:
    """把 JSON 里的 dict 转回 EmojiItem，方便复用卡片渲染/主题检测。"""
    return EmojiItem(
        id=str(data.get("id", "")),
        title=str(data.get("title", "")),
        source=str(data.get("source", "")),
        page_url=str(data.get("page_url", "")),
        image_url=str(data.get("image_url", "")),
        score=float(data.get("score") or 0),
        published_at=str(data.get("published_at", "")),
        tags=list(data.get("tags") or []),
    )


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
            f'<img src="{img}" alt="{title}" loading="lazy" referrerpolicy="no-referrer" '
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
    summary = build_summary(items)
    summary_text = html.escape(summary["text"], quote=True)
    if summary["top"]:
        top_links = " · ".join(
            f'<a href="{html.escape(item.get("page_url", "#"), quote=True)}" target="_blank" rel="noopener">{html.escape(item.get("title", "").replace("[公众号] ", "")[:20], quote=True)}</a>'
            for item in summary["top"]
        )
    else:
        top_links = ""
    if summary.get("themes"):
        theme_chips = []
        for theme in summary["themes"]:
            theme_name = html.escape(theme["name"], quote=True)
            theme_page = html.escape(theme.get("page", "#"), quote=True)
            theme_img = html.escape(theme.get("image", ""), quote=True)
            if theme_img:
                theme_chips.append(
                    f'<a class="theme-chip" href="{theme_page}" target="_blank" rel="noopener">'
                    f'<img src="{theme_img}" alt="{theme_name}" loading="lazy" referrerpolicy="no-referrer" '
                    f'onerror="this.style.display=\'none\'">'
                    f"<span>{theme_name} · {theme['count']}篇</span></a>"
                )
            else:
                theme_chips.append(
                    f'<span class="theme-chip no-img">{theme_name} · {theme["count"]}篇</span>'
                )
        themes_html = (
            '<div class="summary-themes">🔥 今日热门梗：' + "".join(theme_chips) + "</div>"
        )
    else:
        themes_html = '<div class="summary-themes">🔥 今日热门梗：暂无明显重复梗</div>'
    summary_html = (
        '<div class="summary-box">'
        '<div class="summary-title">📌 今日推荐</div>'
        f'<div class="summary-text">{summary_text}</div>'
        f'<div class="summary-links">{top_links}</div>'
        f"{themes_html}"
        "</div>"
    )
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeepSeek 每日表情雷达 · {today}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f7; color: #222; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px 16px 60px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .summary-box {{ background: #fff8e6; border: 1px solid #ffe1a8; border-radius: 12px; padding: 14px 16px; margin-bottom: 20px; }}
  .summary-title {{ font-size: 16px; font-weight: 700; margin-bottom: 6px; }}
  .summary-text {{ font-size: 14px; line-height: 1.7; color: #333; }}
  .summary-links {{ margin-top: 8px; font-size: 13px; }}
  .summary-links a {{ color: #1677ff; text-decoration: none; margin-right: 8px; }}
  .summary-links a:hover {{ text-decoration: underline; }}
  .summary-themes {{ margin-top: 8px; font-size: 13px; color: #b45309; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  .theme-chip {{ display: inline-flex; align-items: center; gap: 6px; background: #fff; border: 1px solid #ffe1a8; border-radius: 999px; padding: 4px 10px 4px 4px; color: #333; text-decoration: none; font-size: 12px; }}
  .theme-chip img {{ width: 32px; height: 32px; object-fit: cover; border-radius: 50%; background: #eee; }}
  .theme-chip.no-img {{ padding: 4px 10px; background: #fff8e6; }}
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
  .topbar {{ display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
  footer {{ margin-top: 40px; text-align: center; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <a class="back" href="index.html">← 返回日报索引</a>
    <a class="back" href="search.html">🔍 搜索老梗</a>
  </div>
  <h1>🧭 DeepSeek 每日表情雷达 · {today}</h1>
  <div class="sub">自动生成于 {human_time(generated_at)} · 共 {len(items)} 条 · 仅收录外链，使用请注意来源与版权</div>
  {summary_html}
  <div class="grid">
{cards}
  </div>
  <footer>🪄 Powered by DeepSeek · 每日自动采集 · 仅外链聚合</footer>
</div>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")


def write_index_html(
    docs_dir: Path,
    days: list[str],
    latest_items: list[dict] | None = None,
    all_items: list[dict] | None = None,
    recent_themes: list[dict] | None = None,
) -> None:
    """生成一站式主页：最近热门梗 + 搜索框 + 最新表情墙都在同一个页面。"""
    latest_items = latest_items or []
    all_items = all_items or []
    recent_themes = recent_themes or []
    data_json = json.dumps(all_items, ensure_ascii=False).replace("</", "<\\/")
    latest_json = json.dumps(latest_items, ensure_ascii=False).replace("</", "<\\/")

    latest_cards = "\n".join(
        _card_html(_dict_to_item(item), i)
        for i, item in enumerate(latest_items, 1)
    ) or '<div class="empty">今天还没有数据，先去 Actions 跑一次。</div>'

    days_links = "\n".join(
        f'    <li><a href="{d}.html">{d}</a></li>' for d in days
    ) or "    <li>暂无历史日报</li>"

    theme_chips = ""
    if recent_themes:
        for theme in recent_themes:
            name = theme["name"]
            escaped = html.escape(name, quote=True)
            count_label = (
                f" · {theme['count']}篇" if theme.get("count") else " · 推荐"
            )
            theme_chips += (
                f'<button class="theme-chip" onclick=\'searchTheme("{escaped}")\'>'
                f"{escaped}{count_label}</button>"
            )
    else:
        theme_chips = '<span class="muted">暂无数据，先去采集或等待日报生成</span>'

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeepSeek 表情雷达</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f7; color: #222; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px 16px 60px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
  .top {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }}
  .search-box {{ display: flex; gap: 8px; flex: 1; min-width: 280px; }}
  .search-box input {{ flex: 1; padding: 10px 14px; border: 2px solid #4d6bfe; border-radius: 999px; font-size: 15px; outline: none; }}
  .search-box input:focus {{ box-shadow: 0 0 0 3px rgba(77,107,254,.2); }}
  .search-box button {{ padding: 10px 18px; border: none; border-radius: 999px; background: #4d6bfe; color: #fff; font-size: 14px; cursor: pointer; }}
  .search-box button:hover {{ background: #3b55e0; }}
  .section {{ background: #fff; border-radius: 12px; padding: 14px 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
  .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 10px; }}
  .theme-chip {{ display: inline-block; margin: 4px 6px 4px 0; padding: 6px 14px; border: 1px solid #ffe1a8; border-radius: 999px; background: #fff8e6; color: #b45309; font-size: 14px; cursor: pointer; }}
  .theme-chip:hover {{ background: #ffe9c7; }}
  .muted {{ color: #999; font-size: 13px; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ margin: 4px 0; }}
  a {{ color: #1677ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
  .card {{ background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; flex-direction: column; }}
  .card a img {{ width: 100%; height: 200px; object-fit: cover; display: block; background: #eee; }}
  .info {{ padding: 10px 12px 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }}
  .title {{ font-size: 14px; font-weight: 600; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .meta {{ color: #888; font-size: 12px; }}
  .page-link {{ color: #1677ff; font-size: 13px; text-decoration: none; margin-top: auto; }}
  .empty {{ text-align: center; color: #999; padding: 40px 0; }}
  footer {{ margin-top: 40px; text-align: center; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="top">
    <div>
      <h1>🧭 DeepSeek 表情雷达</h1>
      <div class="sub">最近热门梗 · 联网搜索 · 最新表情墙，一个页面全搞定</div>
    </div>
    <div class="search-box">
      <input id="q" type="search" placeholder="输入关键词，例如：草地牛 / 猫和老鼠 / 可爱" autocomplete="off">
      <button id="btn" type="button">🔍 联网搜索</button>
    </div>
  </div>

  <div id="status" class="sub">加载中...</div>

  <div class="section">
    <div class="section-title">🔥 最近热门梗（点击自动联网搜索）</div>
    <div id="themes">{theme_chips}</div>
  </div>

  <div class="section">
    <div class="section-title">📅 最近日报</div>
    <ul>
{days_links}
    </ul>
  </div>

  <div class="section">
    <div class="section-title" id="gridTitle">🖼 最新表情墙</div>
    <div id="grid" class="grid">{latest_cards}</div>
  </div>

  <footer>🪄 Powered by DeepSeek · 每日自动采集 · 仅外链聚合</footer>
</div>
<script>
window.__EMOJI_DATA__ = {data_json};
window.__LATEST__ = {latest_json};
const grid = document.getElementById('grid');
const gridTitle = document.getElementById('gridTitle');
const statusEl = document.getElementById('status');
const q = document.getElementById('q');
const btn = document.getElementById('btn');

function cardHtml(x) {{
  const title = x.title || '表情包';
  const img = x.image_url || '';
  const source = x.source || '';
  const date = x.date || '';
  const score = x.score || 0;
  const page = x.page_url || '#';
  return '<div class="card">' +
    (img ? '<a href="' + page + '" target="_blank" rel="noopener"><img src="' + img + '" alt="' + title.replace(/"/g, '&quot;') + '" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\\\'none\\\'"></a>' : '<div class="no-image">暂无图片</div>') +
    '<div class="info">' +
      '<div class="title">' + title.replace(/</g, '&lt;') + '</div>' +
      '<div class="meta">' + source + ' · ' + date + ' · 热度' + Math.round(score) + '</div>' +
      '<a class="page-link" href="' + page + '" target="_blank" rel="noopener">查看来源</a>' +
    '</div></div>';
}}

function render(list, titleHtml, statusHtml) {{
  grid.innerHTML = list.map(cardHtml).join('') || '<div class="empty">没有找到相关表情包，换个关键词试试</div>';
  if (titleHtml !== undefined) gridTitle.innerHTML = titleHtml;
  if (statusHtml !== undefined) statusEl.innerHTML = statusHtml;
}}

function localFilter(kw) {{
  if (!kw) return window.__EMOJI_DATA__;
  return window.__EMOJI_DATA__.filter(function(x) {{
    return ((x.title || '') + ' ' + (x.source || '') + ' ' + (x.date || '')).toLowerCase().includes(kw);
  }});
}}

function renderLocal(kw) {{
  if (!kw) {{
    render(window.__LATEST__, '🖼 最新表情墙', '本地历史共 <b>' + window.__EMOJI_DATA__.length + '</b> 条；输入关键词可搜索，或点“联网搜索”实时搜公众号。');
    return;
  }}
  const list = localFilter(kw.toLowerCase());
  render(list, '🔍 本地搜索结果', '本地历史共 <b>' + list.length + '</b> 条；按回车可联网搜索更多。');
}}

q.addEventListener('input', function() {{
  renderLocal(q.value.trim());
}});

async function onlineSearch(kw) {{
  const keyword = (kw || q.value.trim());
  if (!keyword) {{ q.focus(); return; }}
  q.value = keyword;
  statusEl.textContent = '正在联网搜索“' + keyword + '”...';
  try {{
    const resp = await fetch('/api/search?q=' + encodeURIComponent(keyword));
    const data = await resp.json();
    if (data.items && data.items.length) {{
      const items = data.items.map(function(x) {{ x.date = x.date || ''; return x; }});
      render(items, '🌐 联网搜索结果：' + keyword, '联网搜索到 <b>' + data.count + '</b> 条微信公众号结果（实时）：');
    }} else {{
      renderLocal(keyword);
      statusEl.textContent = '联网没有搜到，已显示本地结果。';
    }}
  }} catch(e) {{
    renderLocal(keyword);
    statusEl.textContent = '联网搜索失败，请确认是用“启动本地网页.bat”启动的服务器。已显示本地结果。';
  }}
}}

function searchTheme(name) {{
  onlineSearch(name);
}}

btn.addEventListener('click', function() {{ onlineSearch(); }});
q.addEventListener('keydown', function(e) {{ if (e.key === 'Enter') onlineSearch(); }});

renderLocal('');
</script>
</body>
</html>
"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "index.html").write_text(html_doc, encoding="utf-8")


def write_search_html(docs_dir: Path, items: list[dict]) -> None:
    """生成老梗搜索页：把所有历史 JSON 的表情包汇总到前端，支持关键词过滤。"""
    # 避免 </script> 截断页面
    data_json = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DeepSeek 老梗搜索</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f7; color: #222; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px 16px 60px; }}
  .top {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }}
  h1 {{ font-size: 24px; margin: 0; }}
  .search-box {{ display: flex; gap: 8px; }}
  .search-box input {{ flex: 1; min-width: 220px; padding: 10px 14px; border: 2px solid #4d6bfe; border-radius: 999px; font-size: 15px; outline: none; }}
  .search-box input:focus {{ box-shadow: 0 0 0 3px rgba(77,107,254,.2); }}
  .search-box button {{ padding: 10px 18px; border: none; border-radius: 999px; background: #4d6bfe; color: #fff; font-size: 14px; cursor: pointer; }}
  .search-box button:hover {{ background: #3b55e0; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
  .card {{ background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; flex-direction: column; }}
  .card a img {{ width: 100%; height: 200px; object-fit: cover; display: block; background: #eee; }}
  .info {{ padding: 10px 12px 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }}
  .title {{ font-size: 14px; font-weight: 600; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .meta {{ color: #888; font-size: 12px; }}
  .page-link {{ color: #1677ff; font-size: 13px; text-decoration: none; margin-top: auto; }}
  .back {{ color: #1677ff; text-decoration: none; font-size: 14px; }}
  .empty {{ text-align: center; color: #999; padding: 60px 0; }}
  footer {{ margin-top: 40px; text-align: center; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="top">
    <div>
      <a class="back" href="index.html">← 返回日报</a>
      <h1>🔍 DeepSeek 老梗搜索</h1>
    </div>
    <div class="search-box">
      <input id="q" type="search" placeholder="输入关键词，例如：草地牛 / 猫和老鼠 / 可爱" autocomplete="off">
      <button id="btn" type="button">🔍 联网搜索</button>
    </div>
  </div>
  <div class="sub"><span id="status">本地历史共 <span id="count">0</span> 条；按回车或点“联网搜索”可实时搜微信公众号。</span></div>
  <div id="grid" class="grid"></div>
  <footer>🪄 Powered by DeepSeek · 每日自动采集 · 仅外链聚合</footer>
</div>
<script>
window.__EMOJI_DATA__ = {data_json};
const grid = document.getElementById('grid');
const statusEl = document.getElementById('status');
const q = document.getElementById('q');
const btn = document.getElementById('btn');

function cardHtml(x) {{
  const title = x.title || '表情包';
  const img = x.image_url || '';
  const source = x.source || '';
  const date = x.date || '';
  const score = x.score || 0;
  const page = x.page_url || '#';
  return '<div class="card">' +
    (img ? '<a href="' + page + '" target="_blank" rel="noopener"><img src="' + img + '" alt="' + title.replace(/"/g, '&quot;') + '" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\\\'none\\\'"></a>' : '<div class="no-image">暂无图片</div>') +
    '<div class="info">' +
      '<div class="title">' + title.replace(/</g, '&lt;') + '</div>' +
      '<div class="meta">' + source + ' · ' + date + ' · 热度' + Math.round(score) + '</div>' +
      '<a class="page-link" href="' + page + '" target="_blank" rel="noopener">查看来源</a>' +
    '</div></div>';
}}

function render(list, statusHtml) {{
  grid.innerHTML = list.map(cardHtml).join('') || '<div class="empty">没有找到相关表情包，换个关键词试试</div>';
  if (statusHtml !== undefined) {{
    statusEl.innerHTML = statusHtml;
  }}
}}

function localFilter(kw) {{
  if (!kw) return window.__EMOJI_DATA__;
  return window.__EMOJI_DATA__.filter(function(x) {{
    return ((x.title || '') + ' ' + (x.source || '') + ' ' + (x.date || '')).toLowerCase().includes(kw);
  }});
}}

function renderLocal(kw) {{
  const list = localFilter(kw);
  render(list, '本地历史共 <b>' + list.length + '</b> 条；按回车或点“联网搜索”可实时搜微信公众号。');
}}

q.addEventListener('input', function() {{
  renderLocal(q.value.trim().toLowerCase());
}});

async function onlineSearch() {{
  const kw = q.value.trim();
  if (!kw) {{ q.focus(); return; }}
  statusEl.textContent = '正在联网搜索“' + kw + '”...';
  try {{
    const resp = await fetch('/api/search?q=' + encodeURIComponent(kw));
    const data = await resp.json();
    if (data.items && data.items.length) {{
      const items = data.items.map(function(x) {{ x.date = x.date || ''; return x; }});
      render(items, '联网搜索到 <b>' + data.count + '</b> 条微信公众号结果（实时）：');
    }} else {{
      renderLocal(kw.toLowerCase());
      statusEl.textContent = '联网没有搜到，已显示本地结果。';
    }}
  }} catch(e) {{
    renderLocal(kw.toLowerCase());
    statusEl.textContent = '联网搜索失败，请确认是用“启动本地网页.bat”启动的服务器。已显示本地结果。';
  }}
}}

btn.addEventListener('click', onlineSearch);
q.addEventListener('keydown', function(e) {{ if (e.key === 'Enter') onlineSearch(); }});

renderLocal('');
</script>
</body>
</html>
"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "search.html").write_text(html_doc, encoding="utf-8")


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
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="过滤掉超过 N 天的旧图；0 表示不过滤。默认 0（不过滤，但新的会排在前面）",
    )
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

    # 网页只展示有图的，避免出现“暂无图片”的空白卡片。
    before_img = len(merged)
    merged = [item for item in merged if item.image_url]
    if len(merged) != before_img:
        print(f"[filter] removed {before_img - len(merged)} items without images")

    if args.max_age_days > 0:
        cutoff_ts = datetime.now(timezone.utc).timestamp() - args.max_age_days * 86400
        before = len(merged)
        merged = [
            item
            for item in merged
            if _date_sort_key(item) == 0.0 or _date_sort_key(item) >= cutoff_ts
        ]
        print(f"[filter] removed {before - len(merged)} items older than {args.max_age_days} days")

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
    # 汇总所有历史 JSON，生成老梗搜索页 + 一站式主页。
    search_items: list[dict] = []
    recent_emoji_items: list[EmojiItem] = []
    recent_cutoff = date.today() - timedelta(days=90)
    for p in sorted(output_dir.glob("????-??-??.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("items", []):
            item = dict(item)
            item["date"] = p.stem
            search_items.append(item)
            try:
                fdate = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if fdate >= recent_cutoff:
                recent_emoji_items.append(_dict_to_item(item))

    recent_themes = detect_hot_themes(
        recent_emoji_items, min_count=2, min_accounts=2, max_themes=12
    )
    # 真实热门梗不够时，用常见热门梗关键词补足，保证主页始终有可选梗。
    curated_themes = [
        "草地牛", "猫和老鼠", "线条小狗", "黄油小熊", "Loopy",
        "卡皮巴拉", "吗喽", "悲伤蛙", "熊猫头", "捂脸", "裂开", "早八",
    ]
    existing_names = {t["name"] for t in recent_themes}
    for name in curated_themes:
        if len(recent_themes) >= 12:
            break
        if name not in existing_names:
            recent_themes.append(
                {"name": name, "count": 0, "accounts": 0, "image": "", "page": ""}
            )
    latest_items: list[dict] = []
    for item in merged:
        d = item.to_dict()
        d["date"] = today
        latest_items.append(d)

    write_index(docs_dir, all_days[:30])
    write_index_html(docs_dir, all_days[:30], latest_items, search_items, recent_themes)
    write_search_html(docs_dir, search_items)

    prune_old(output_dir, docs_dir, keep_days)

    print(f"[done] {len(merged)} items -> {json_path} / {md_path} / {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
