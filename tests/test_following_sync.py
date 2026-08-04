import json

import yaml

from tools.following_sync import (
    collect_following,
    keep_previous_snapshot_available,
    normalize_author,
    write_outputs,
)


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def get_following_page(
        self,
        sec_uid,
        *,
        user_id=None,
        max_time=0,
        offset=0,
        count=20,
    ):
        self.calls.append((sec_uid, user_id, max_time, offset, count))
        if max_time == 0 and offset == 0:
            return {
                "items": [
                    {"sec_uid": "a", "nickname": "甲"},
                    {"user": {"sec_uid": "b", "nickname": "乙"}},
                ],
                "has_more": 1,
                "min_time": 123,
                "offset": 20,
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
    authors = await collect_following(
        api,
        "self-sec",
        user_id="self-uid",
        delay_seconds=0,
    )
    assert [author["sec_uid"] for author in authors] == ["a", "b", "c"]
    assert authors[1]["nickname"] == "乙-新"
    assert api.calls == [
        ("self-sec", "self-uid", 0, 0, 20),
        ("self-sec", "self-uid", 123, 20, 20),
    ]


class BrokenPaginationAPI:
    async def get_following_page(self, *_args, **_kwargs):
        return {
            "items": [{"sec_uid": "a", "nickname": "甲"}],
            "has_more": 1,
            "min_time": 0,
            "offset": 0,
        }


async def test_collect_following_rejects_incomplete_page_without_cursor():
    import pytest

    with pytest.raises(RuntimeError, match="分页中断"):
        await collect_following(BrokenPaginationAPI(), "self-sec", delay_seconds=0)


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


def test_failed_refresh_keeps_old_snapshot_available_without_losing_authors(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    snapshot_file = state_dir / "following.json"
    old_time = "2026-08-03T00:00:00+00:00"
    authors = [
        {"sec_uid": "a", "nickname": "甲"},
        {"sec_uid": "b", "nickname": "乙"},
    ]
    snapshot_file.write_text(
        json.dumps(
            {"synced_at": old_time, "count": 2, "authors": authors},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert keep_previous_snapshot_available(state_dir) is True

    payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["authors"] == authors
    assert payload["data_synced_at"] == old_time
    assert payload["synced_at"] != old_time
    assert payload["last_refresh_failed_at"] == payload["synced_at"]
