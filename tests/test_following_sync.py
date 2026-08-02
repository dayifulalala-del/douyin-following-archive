import yaml

from tools.following_sync import collect_following, normalize_author, write_outputs


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def get_following_page(self, sec_uid, *, max_time=0, count=20):
        self.calls.append((sec_uid, max_time, count))
        if max_time == 0:
            return {
                "items": [
                    {"sec_uid": "a", "nickname": "甲"},
                    {"user": {"sec_uid": "b", "nickname": "乙"}},
                ],
                "has_more": 1,
                "min_time": 123,
            }
        return {
            "items": [
                {"sec_uid": "b", "nickname": "乙-新"},
                {"sec_uid": "c", "nickname": "丙"},
            ],
            "has_more": 0,
            "min_time": 0,
        }


def test_normalize_author_accepts_nested_user():
    author = normalize_author({"user": {"sec_uid": "sec-1", "nickname": "作者"}})
    assert author["url"] == "https://www.douyin.com/user/sec-1"
    assert author["nickname"] == "作者"


def test_normalize_author_keeps_avatar_url():
    author = normalize_author(
        {
            "sec_uid": "sec-1",
            "uid": "uid-1",
            "nickname": "作者",
            "avatar_thumb": {"url_list": ["https://example.com/avatar.jpg"]},
            "aweme_count": 12,
        }
    )

    assert author["avatar_url"] == "https://example.com/avatar.jpg"
    assert author["aweme_count"] == 12


async def test_collect_following_paginates_and_deduplicates():
    api = FakeAPI()
    authors = await collect_following(api, "self-sec", delay_seconds=0)
    assert [author["sec_uid"] for author in authors] == ["a", "b", "c"]
    assert authors[1]["nickname"] == "乙-新"
    assert api.calls == [("self-sec", 0, 20), ("self-sec", 123, 20)]


def test_write_outputs_forces_browser_fallback_to_background(tmp_path):
    base_config = tmp_path / "config.yml"
    base_config.write_text(
        yaml.safe_dump(
            {
                "browser_fallback": {"enabled": True, "headless": False},
                "number": {},
                "increase": {},
            }
        ),
        encoding="utf-8",
    )

    generated = write_outputs(
        base_config_path=base_config,
        state_dir=tmp_path / "state",
        download_dir=tmp_path / "downloads",
        self_info={"sec_uid": "self"},
        authors=[{"sec_uid": "author", "url": "https://www.douyin.com/user/author"}],
    )

    config = yaml.safe_load(generated.read_text(encoding="utf-8"))
    assert config["browser_fallback"]["enabled"] is True
    assert config["browser_fallback"]["headless"] is True
