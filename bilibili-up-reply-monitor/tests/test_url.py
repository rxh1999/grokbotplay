from bilibili_monitor.url import extract_bvid, is_short_link, normalize_video_url


def test_extract_bvid_from_url():
    assert extract_bvid("https://www.bilibili.com/video/BV1pXHS6iEZQ/") == "BV1pXHS6iEZQ"
    assert extract_bvid("https://www.bilibili.com/video/BV1pXHS6iEZQ?p=1") == "BV1pXHS6iEZQ"


def test_extract_bvid_raw():
    assert extract_bvid("BV1pXHS6iEZQ") == "BV1pXHS6iEZQ"
    assert extract_bvid("看这个 BV1pXHS6iEZQ 视频") == "BV1pXHS6iEZQ"


def test_extract_bvid_none():
    assert extract_bvid("") is None
    assert extract_bvid("https://example.com/") is None


def test_short_link_hosts():
    assert is_short_link("https://b23.tv/KGXJu1o")
    assert is_short_link("https://bili2233.cn/abc")
    assert not is_short_link("https://www.bilibili.com/video/BV1pXHS6iEZQ")


def test_normalize():
    assert normalize_video_url("BV1pXHS6iEZQ") == "https://www.bilibili.com/video/BV1pXHS6iEZQ"
