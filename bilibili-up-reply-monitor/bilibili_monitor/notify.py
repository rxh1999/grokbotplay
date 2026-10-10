from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from bilibili_monitor.models import Reply, VideoInfo

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def format_ctime(ts: int) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(SHANGHAI)
    return dt.strftime("%Y-%m-%d %H:%M:%S CST")


def build_text(video: VideoInfo, reply: Reply) -> str:
    link = reply.permalink() or video.url
    return (
        f"[B站 UP主新回复]\n"
        f"视频: {video.title}\n"
        f"UP: {video.owner_name} (mid={video.owner_mid})\n"
        f"时间: {format_ctime(reply.ctime)}\n"
        f"内容: {reply.message}\n"
        f"链接: {link}"
    )


class Notifier(ABC):
    @abstractmethod
    def send(self, video: VideoInfo, reply: Reply) -> None:
        raise NotImplementedError


class PrintNotifier(Notifier):
    """Dry-run / once mode: print to stdout only."""

    def send(self, video: VideoInfo, reply: Reply) -> None:
        print(build_text(video, reply))
        print("-" * 40)


class WebhookNotifier(Notifier):
    """Generic webhook: POST JSON. Primary notification channel.

    Default payload shape (custom URL):
      {
        "text": "...",
        "title": "...",
        "video": {...},
        "reply": {...}
      }

    Set WEBHOOK_STYLE=feishu|lark|dingtalk|custom to wrap provider-specific bodies.
    """

    def __init__(
        self,
        url: str,
        *,
        style: str = "custom",
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ):
        self.url = url
        self.style = (style or "custom").lower()
        self._owns = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def _payload(self, video: VideoInfo, reply: Reply) -> dict[str, Any]:
        text = build_text(video, reply)
        link = reply.permalink() or video.url
        base = {
            "text": text,
            "title": f"UP主新回复 · {video.title}",
            "video": {
                "bvid": video.bvid,
                "aid": video.aid,
                "title": video.title,
                "url": video.url,
                "owner_mid": video.owner_mid,
                "owner_name": video.owner_name,
            },
            "reply": {
                "rpid": reply.rpid,
                "mid": reply.mid,
                "uname": reply.uname,
                "message": reply.message,
                "ctime": reply.ctime,
                "ctime_text": format_ctime(reply.ctime),
                "root": reply.root,
                "parent": reply.parent,
                "link": link,
            },
        }
        if self.style in ("feishu", "lark"):
            # Feishu / Lark custom bot text message
            return {"msg_type": "text", "content": {"text": text}}
        if self.style == "dingtalk":
            return {"msgtype": "text", "text": {"content": text}}
        return base

    def send(self, video: VideoInfo, reply: Reply) -> None:
        payload = self._payload(video, reply)
        resp = self._client.post(self.url, json=payload)
        resp.raise_for_status()
        # Feishu/DingTalk often return JSON with errcode/StatusCode
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            logger.info("Webhook OK status=%s", resp.status_code)
            return
        err = body.get("code", body.get("StatusCode", body.get("errcode", 0)))
        if err not in (0, "0", None):
            raise RuntimeError(f"Webhook provider error: {body}")
        logger.info("Webhook delivered: %s", json.dumps(body, ensure_ascii=False)[:200])


class TelegramNotifier(Notifier):
    """Optional Telegram Bot API notifier."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._owns = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns:
            self._client.close()

    def send(self, video: VideoInfo, reply: Reply) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        resp = self._client.post(
            url,
            json={"chat_id": self.chat_id, "text": build_text(video, reply)},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram error: {data}")


class MultiNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def send(self, video: VideoInfo, reply: Reply) -> None:
        errors: list[str] = []
        for n in self.notifiers:
            try:
                n.send(video, reply)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Notifier %s failed", type(n).__name__)
                errors.append(f"{type(n).__name__}: {exc}")
        if errors and len(errors) == len(self.notifiers):
            raise RuntimeError("; ".join(errors))

    def close(self) -> None:
        for n in self.notifiers:
            close = getattr(n, "close", None)
            if callable(close):
                close()
