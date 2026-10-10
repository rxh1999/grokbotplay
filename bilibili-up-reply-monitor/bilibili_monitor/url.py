from __future__ import annotations

import re
from urllib.parse import urlparse

BV_RE = re.compile(r"(BV[\w]+)", re.IGNORECASE)
SHORT_HOSTS = {"b23.tv", "bili2233.cn", "bili22.cn", "bili23.cn", "bili33.cn"}


def extract_bvid(text: str) -> str | None:
    """Extract a BV id from a URL or free-form string."""
    if not text:
        return None
    m = BV_RE.search(text.strip())
    if not m:
        return None
    return m.group(1) if m.group(1).startswith("BV") else "BV" + m.group(1)[2:]


def is_short_link(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    host = host.removeprefix("www.")
    return host in SHORT_HOSTS


def normalize_video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"
