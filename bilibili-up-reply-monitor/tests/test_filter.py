from bilibili_monitor.models import Reply, VideoInfo
from bilibili_monitor.monitor import filter_by_mid
from bilibili_monitor.client import BilibiliClient
from bilibili_monitor.notify import WebhookNotifier, build_text
from bilibili_monitor.store import SeenStore


def _reply(rpid: int, mid: int, message: str = "hi", **kw) -> Reply:
    return Reply(
        rpid=rpid,
        mid=mid,
        uname="u",
        message=message,
        ctime=1,
        root=kw.get("root", 0),
        parent=kw.get("parent", 0),
        bvid="BV1pXHS6iEZQ",
    )


def test_filter_by_mid():
    replies = [
        _reply(1, 100, "a"),
        _reply(2, 200, "b"),
        _reply(3, 100, "c", root=1, parent=1),
    ]
    got = filter_by_mid(replies, 100)
    assert [r.rpid for r in got] == [1, 3]


def test_reply_permalink_top_and_nested():
    top = _reply(10, 1)
    assert "comment_root_id=10" in top.permalink()
    assert "comment_secondary_id" not in top.permalink()

    nested = _reply(20, 1, root=10, parent=10)
    link = nested.permalink()
    assert "comment_root_id=10" in link
    assert "comment_secondary_id=20" in link


def test_reply_from_api():
    raw = {
        "rpid": 99,
        "mid": 3493130286402061,
        "ctime": 123,
        "root": 0,
        "parent": 0,
        "like": 3,
        "member": {"uname": "UP", "mid": "3493130286402061"},
        "content": {"message": "你好"},
    }
    r = Reply.from_api(raw, bvid="BV1pXHS6iEZQ")
    assert r.rpid == 99
    assert r.mid == 3493130286402061
    assert r.message == "你好"
    assert r.uname == "UP"


def test_fetch_up_replies_mocked(monkeypatch):
    video = VideoInfo(
        bvid="BV1pXHS6iEZQ",
        aid=117403249808569,
        title="t",
        owner_mid=111,
        owner_name="up",
        url="https://www.bilibili.com/video/BV1pXHS6iEZQ",
    )

    top = [
        {
            "rpid": 1,
            "mid": 999,
            "ctime": 1,
            "root": 0,
            "parent": 0,
            "rcount": 2,
            "member": {"uname": "fan"},
            "content": {"message": "问"},
            "replies": [
                {
                    "rpid": 2,
                    "mid": 111,
                    "ctime": 2,
                    "root": 1,
                    "parent": 1,
                    "member": {"uname": "up"},
                    "content": {"message": "答1"},
                }
            ],
        },
        {
            "rpid": 3,
            "mid": 111,
            "ctime": 3,
            "root": 0,
            "parent": 0,
            "rcount": 0,
            "member": {"uname": "up"},
            "content": {"message": "置顶说"},
            "replies": [],
        },
    ]
    children = [
        {
            "rpid": 2,
            "mid": 111,
            "ctime": 2,
            "root": 1,
            "parent": 1,
            "member": {"uname": "up"},
            "content": {"message": "答1"},
        },
        {
            "rpid": 4,
            "mid": 111,
            "ctime": 4,
            "root": 1,
            "parent": 1,
            "member": {"uname": "up"},
            "content": {"message": "答2"},
        },
        {
            "rpid": 5,
            "mid": 222,
            "ctime": 5,
            "root": 1,
            "parent": 1,
            "member": {"uname": "other"},
            "content": {"message": "路过"},
        },
    ]

    client = BilibiliClient(request_interval=0)

    def fake_top(aid, mode=2, max_pages=50):
        assert aid == video.aid
        yield from top

    def fake_child(aid, root_rpid, ps=20, max_pages=100):
        assert root_rpid == 1
        yield from children

    monkeypatch.setattr(client, "iter_top_replies", fake_top)
    monkeypatch.setattr(client, "iter_child_replies", fake_child)

    got = client.fetch_up_replies(video, expand_children=True)
    assert [r.rpid for r in got] == [2, 3, 4]
    assert all(r.mid == 111 for r in got)


def test_store_baseline(tmp_path):
    db = tmp_path / "seen.sqlite3"
    store = SeenStore(db)
    assert not store.is_baselined("BV1")
    store.add_many("BV1", [1, 2, 3], ts=100)
    store.mark_baselined("BV1")
    assert store.is_baselined("BV1")
    assert store.known(2)
    assert not store.known(9)
    assert store.add_many("BV1", [2, 9], ts=101) == 1
    store.close()


def test_webhook_feishu_payload():
    video = VideoInfo(
        bvid="BV1pXHS6iEZQ",
        aid=1,
        title="标题",
        owner_mid=1,
        owner_name="up",
        url="https://www.bilibili.com/video/BV1pXHS6iEZQ",
    )
    reply = _reply(10, 1, "内容")
    n = WebhookNotifier("https://example.com/hook", style="feishu")
    payload = n._payload(video, reply)
    assert payload["msg_type"] == "text"
    assert "内容" in payload["content"]["text"]

    n2 = WebhookNotifier("https://example.com/hook", style="dingtalk")
    p2 = n2._payload(video, reply)
    assert p2["msgtype"] == "text"

    text = build_text(video, reply)
    assert "标题" in text and "内容" in text
