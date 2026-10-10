from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VideoInfo:
    bvid: str
    aid: int
    title: str
    owner_mid: int
    owner_name: str
    url: str


@dataclass(frozen=True)
class Reply:
    rpid: int
    mid: int
    uname: str
    message: str
    ctime: int
    root: int
    parent: int
    like: int = 0
    bvid: str = ""

    @property
    def is_top_level(self) -> bool:
        return int(self.root or 0) == 0

    def permalink(self) -> str:
        if not self.bvid:
            return ""
        base = f"https://www.bilibili.com/video/{self.bvid}"
        if self.is_top_level:
            return f"{base}?comment_on=1&comment_root_id={self.rpid}"
        root = self.root or self.parent
        return (
            f"{base}?comment_on=1&comment_root_id={root}"
            f"&comment_secondary_id={self.rpid}"
        )

    @classmethod
    def from_api(cls, raw: dict[str, Any], *, bvid: str = "") -> "Reply":
        member = raw.get("member") or {}
        content = raw.get("content") or {}
        mid = raw.get("mid")
        if mid is None:
            mid = member.get("mid")
        return cls(
            rpid=int(raw["rpid"]),
            mid=int(mid),
            uname=str(member.get("uname") or ""),
            message=str(content.get("message") or ""),
            ctime=int(raw.get("ctime") or 0),
            root=int(raw.get("root") or 0),
            parent=int(raw.get("parent") or 0),
            like=int(raw.get("like") or 0),
            bvid=bvid,
        )


@dataclass
class MonitorState:
    video: VideoInfo
    seen_rpids: set[int] = field(default_factory=set)
    baseline_done: bool = False
