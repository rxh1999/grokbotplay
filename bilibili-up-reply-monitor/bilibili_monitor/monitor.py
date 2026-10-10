from __future__ import annotations

import logging
import time
from typing import Iterable

from bilibili_monitor.client import BilibiliClient
from bilibili_monitor.models import Reply, VideoInfo
from bilibili_monitor.notify import Notifier
from bilibili_monitor.store import SeenStore

logger = logging.getLogger(__name__)


class UpReplyMonitor:
    def __init__(
        self,
        client: BilibiliClient,
        store: SeenStore,
        notifier: Notifier,
        *,
        video_ref: str,
        interval: float = 45.0,
        expand_children: bool = True,
    ):
        self.client = client
        self.store = store
        self.notifier = notifier
        self.video_ref = video_ref
        self.interval = interval
        self.expand_children = expand_children
        self.video: VideoInfo | None = None

    def load_video(self) -> VideoInfo:
        self.video = self.client.get_video(self.video_ref)
        logger.info(
            "Video %s aid=%s UP=%s(%s) title=%s",
            self.video.bvid,
            self.video.aid,
            self.video.owner_name,
            self.video.owner_mid,
            self.video.title,
        )
        return self.video

    def fetch_up_replies(self) -> list[Reply]:
        if self.video is None:
            self.load_video()
        assert self.video is not None
        return self.client.fetch_up_replies(
            self.video, expand_children=self.expand_children
        )

    def run_once(self, *, notify: bool = True, force_baseline: bool = False) -> list[Reply]:
        """Fetch once. First successful run baselines without notify unless force.

        Returns the list of *new* UP replies (empty on baseline).
        """
        video = self.video or self.load_video()
        replies = self.fetch_up_replies()
        now = int(time.time())
        baselined = self.store.is_baselined(video.bvid)

        if not baselined or force_baseline:
            self.store.add_many(video.bvid, [r.rpid for r in replies], ts=now)
            self.store.mark_baselined(video.bvid)
            logger.info(
                "Baseline complete for %s: %d UP replies recorded, no notifications",
                video.bvid,
                len(replies),
            )
            return []

        new_replies: list[Reply] = []
        for reply in replies:
            if self.store.known(reply.rpid):
                continue
            new_replies.append(reply)

        for reply in new_replies:
            logger.info("New UP reply rpid=%s: %s", reply.rpid, reply.message[:80])
            if notify:
                self.notifier.send(video, reply)
            self.store.add_many(video.bvid, [reply.rpid], ts=now)

        if not new_replies:
            logger.info("No new UP replies (%d known)", len(replies))
        return new_replies

    def run_forever(self) -> None:
        self.load_video()
        # Always baseline / poll immediately once
        self.run_once(notify=True)
        while True:
            time.sleep(self.interval)
            try:
                self.run_once(notify=True)
            except Exception:  # noqa: BLE001
                logger.exception("Poll failed; will retry after interval")


def filter_by_mid(replies: Iterable[Reply], mid: int) -> list[Reply]:
    mid_i = int(mid)
    return [r for r in replies if int(r.mid) == mid_i]
