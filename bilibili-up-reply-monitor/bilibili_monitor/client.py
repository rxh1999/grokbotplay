from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import httpx

from bilibili_monitor.models import Reply, VideoInfo
from bilibili_monitor.url import extract_bvid, is_short_link, normalize_video_url

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Public endpoints verified working without login (as of 2026-10):
# - GET https://api.bilibili.com/x/web-interface/wbi/view?bvid=...
# - GET https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=2&next=...
# - GET https://api.bilibili.com/x/v2/reply/reply?type=1&oid={aid}&root={rpid}&pn=&ps=
# Note: /x/web-interface/view may return HTTP 412 from some datacenter IPs;
# the wbi/view variant is more reliable. Cookies (SESSDATA) are optional;
# public videos usually work without login. Aggressive polling may trigger -352.


class BilibiliError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None):
        super().__init__(message)
        self.code = code


class BilibiliClient:
    def __init__(
        self,
        *,
        cookie: str | None = None,
        timeout: float = 20.0,
        request_interval: float = 0.25,
        client: httpx.Client | None = None,
    ):
        self.request_interval = request_interval
        self._last_request = 0.0
        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        }
        if cookie:
            headers["Cookie"] = cookie
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BilibiliClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self.request_interval - (now - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._throttle()
        resp = self._client.get(url, params=params)
        # Some anti-bot pages return HTML with 412
        if resp.status_code == 412:
            raise BilibiliError(
                "HTTP 412 from Bilibili (anti-bot). "
                "Try setting BILIBILI_COOKIE (buvid3/SESSDATA from browser), "
                "slowing the poll interval, or running from a residential IP.",
                code=412,
            )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise BilibiliError(f"Non-JSON response from {url}: {exc}") from exc
        code = data.get("code")
        if code not in (0, None):
            raise BilibiliError(
                f"API error code={code} message={data.get('message')!r} url={url}",
                code=int(code) if code is not None else None,
            )
        return data

    def resolve_url(self, url_or_bvid: str) -> str:
        """Resolve short links / raw BV to a canonical video URL and return BV id."""
        text = url_or_bvid.strip()
        bvid = extract_bvid(text)
        if bvid and not is_short_link(text):
            return bvid

        if text.startswith("http://") or text.startswith("https://"):
            # Follow redirects manually so we can read BV from Location
            # without downloading the (sometimes 412) HTML video page.
            self._throttle()
            resp = self._client.get(text, follow_redirects=False)
            candidates = [text, str(resp.headers.get("location") or ""), str(resp.url)]
            # One more hop if still on a short host
            loc = resp.headers.get("location")
            if loc and is_short_link(text) and resp.is_redirect:
                self._throttle()
                resp2 = self._client.get(loc, follow_redirects=False)
                candidates.extend(
                    [loc, str(resp2.headers.get("location") or ""), str(resp2.url)]
                )
            for cand in candidates:
                bvid = extract_bvid(cand)
                if bvid:
                    return bvid
            # Last resort: full follow (page may 412 but URL often still has BV)
            self._throttle()
            resp = self._client.get(text, follow_redirects=True)
            bvid = extract_bvid(str(resp.url)) or extract_bvid(text)
            if not bvid:
                raise BilibiliError(
                    f"Could not extract BV id from {text!r} -> {resp.url!r}"
                )
            return bvid

        bvid = extract_bvid(text)
        if not bvid:
            raise BilibiliError(f"Could not parse BV id from {text!r}")
        return bvid

    def get_video(self, bvid_or_url: str) -> VideoInfo:
        bvid = self.resolve_url(bvid_or_url)
        data = self._get_json(
            "https://api.bilibili.com/x/web-interface/wbi/view",
            {"bvid": bvid},
        )
        info = data["data"]
        owner = info.get("owner") or {}
        return VideoInfo(
            bvid=str(info["bvid"]),
            aid=int(info["aid"]),
            title=str(info.get("title") or ""),
            owner_mid=int(owner["mid"]),
            owner_name=str(owner.get("name") or ""),
            url=normalize_video_url(str(info["bvid"])),
        )

    def iter_top_replies(self, aid: int, *, mode: int = 2, max_pages: int = 50) -> Iterator[dict[str, Any]]:
        """Yield raw top-level reply objects, newest/hot depending on mode.

        mode=2: sort by time (推荐用于监控新回复)
        mode=3: sort by hot
        """
        next_cursor: int | str = 0
        for _ in range(max_pages):
            data = self._get_json(
                "https://api.bilibili.com/x/v2/reply/main",
                {"type": 1, "oid": aid, "mode": mode, "next": next_cursor},
            )
            payload = data.get("data") or {}
            replies = payload.get("replies") or []
            for item in replies:
                yield item
            cursor = payload.get("cursor") or {}
            if cursor.get("is_end"):
                break
            nxt = cursor.get("next")
            if nxt is None or nxt == next_cursor:
                break
            next_cursor = nxt

    def iter_child_replies(
        self, aid: int, root_rpid: int, *, ps: int = 20, max_pages: int = 100
    ) -> Iterator[dict[str, Any]]:
        for pn in range(1, max_pages + 1):
            data = self._get_json(
                "https://api.bilibili.com/x/v2/reply/reply",
                {"type": 1, "oid": aid, "root": root_rpid, "pn": pn, "ps": ps},
            )
            payload = data.get("data") or {}
            replies = payload.get("replies") or []
            if not replies:
                break
            for item in replies:
                yield item
            page = payload.get("page") or {}
            count = int(page.get("count") or 0)
            if pn * ps >= count:
                break

    def fetch_up_replies(
        self,
        video: VideoInfo,
        *,
        expand_children: bool = True,
        mode: int = 2,
        max_pages: int = 50,
    ) -> list[Reply]:
        """Collect replies authored by the video owner (UP主), including nested."""
        up_mid = int(video.owner_mid)
        found: dict[int, Reply] = {}

        for raw in self.iter_top_replies(video.aid, mode=mode, max_pages=max_pages):
            if int(raw.get("mid") or 0) == up_mid:
                reply = Reply.from_api(raw, bvid=video.bvid)
                found[reply.rpid] = reply

            inline = raw.get("replies") or []
            for sub in inline:
                if int(sub.get("mid") or 0) == up_mid:
                    reply = Reply.from_api(sub, bvid=video.bvid)
                    found[reply.rpid] = reply

            if not expand_children:
                continue
            rcount = int(raw.get("rcount") or 0)
            if rcount <= len(inline):
                continue
            root_rpid = int(raw["rpid"])
            try:
                for sub in self.iter_child_replies(video.aid, root_rpid):
                    if int(sub.get("mid") or 0) == up_mid:
                        reply = Reply.from_api(sub, bvid=video.bvid)
                        found[reply.rpid] = reply
            except BilibiliError as exc:
                logger.warning("Failed to expand children of %s: %s", root_rpid, exc)

        return sorted(found.values(), key=lambda r: (r.ctime, r.rpid))
