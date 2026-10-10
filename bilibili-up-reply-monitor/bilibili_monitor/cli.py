from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from bilibili_monitor.client import BilibiliClient
from bilibili_monitor.monitor import UpReplyMonitor
from bilibili_monitor.notify import (
    MultiNotifier,
    Notifier,
    PrintNotifier,
    TelegramNotifier,
    WebhookNotifier,
)
from bilibili_monitor.store import SeenStore

DEFAULT_VIDEO = "https://b23.tv/KGXJu1o"
DEFAULT_DB = "data/seen.sqlite3"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        os.environ.setdefault(key, val)


def build_notifier(*, dry_run: bool) -> Notifier:
    if dry_run:
        return PrintNotifier()

    notifiers: list[Notifier] = []
    webhook = os.environ.get("WEBHOOK_URL", "").strip()
    if webhook:
        style = os.environ.get("WEBHOOK_STYLE", "custom").strip() or "custom"
        notifiers.append(WebhookNotifier(webhook, style=style))

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        notifiers.append(TelegramNotifier(tg_token, tg_chat))

    if not notifiers:
        logging.getLogger(__name__).warning(
            "No WEBHOOK_URL / Telegram configured; falling back to stdout"
        )
        return PrintNotifier()
    if len(notifiers) == 1:
        return notifiers[0]
    return MultiNotifier(notifiers)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bilibili-monitor",
        description="监控 B 站视频下 UP 主评论/回复，并通过 Webhook 推送新内容",
    )
    p.add_argument(
        "--video",
        default=os.environ.get("VIDEO_URL", DEFAULT_VIDEO),
        help=f"视频链接或 BV 号 (默认: {DEFAULT_VIDEO})",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("POLL_INTERVAL", "45")),
        help="轮询间隔秒数 (默认 45)",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("DB_PATH", DEFAULT_DB),
        help="SQLite 路径，记录已见 rpid",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="只拉取一次后退出（首次会做 baseline）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="不发送通知，只打印匹配到的 UP 回复",
    )
    p.add_argument(
        "--show-all",
        action="store_true",
        help="与 --dry-run/--once 合用：打印当前所有 UP 回复（不做 baseline 跳过）",
    )
    p.add_argument(
        "--no-expand",
        action="store_true",
        help="不展开楼中楼（只看主楼 + 内联几条回复）",
    )
    p.add_argument(
        "--cookie",
        default=os.environ.get("BILIBILI_COOKIE", ""),
        help="可选 Cookie（如 buvid3; SESSDATA=...），对抗 412/-352",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(Path(".env"))
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = BilibiliClient(cookie=args.cookie or None)
    store = SeenStore(args.db)
    notifier = build_notifier(dry_run=args.dry_run)

    mon = UpReplyMonitor(
        client,
        store,
        notifier,
        video_ref=args.video,
        interval=args.interval,
        expand_children=not args.no_expand,
    )

    try:
        video = mon.load_video()
        print(
            f"监控视频: {video.title}\n"
            f"BV={video.bvid} aid={video.aid}\n"
            f"UP={video.owner_name} mid={video.owner_mid}\n"
            f"URL={video.url}"
        )

        if args.show_all:
            replies = mon.fetch_up_replies()
            print(f"当前 UP 回复共 {len(replies)} 条:")
            for r in replies:
                notifier.send(video, r)
            return 0

        if args.once or args.dry_run:
            # dry-run once: baseline silently unless already baselined,
            # then print any "new" (usually none on first run)
            new = mon.run_once(notify=True)
            if args.dry_run and not new and not store.is_baselined(video.bvid):
                pass
            print(f"本轮新 UP 回复: {len(new)}")
            return 0

        mon.run_forever()
        return 0
    finally:
        close = getattr(notifier, "close", None)
        if callable(close):
            close()
        client.close()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
