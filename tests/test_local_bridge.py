import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection

import pytest
import yaml

import local_bridge


def test_following_snapshot_freshness_expires_old_cache():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    fresh = {"synced_at": (now - timedelta(seconds=5)).isoformat()}
    stale = {"synced_at": (now - timedelta(seconds=301)).isoformat()}

    assert local_bridge.following_snapshot_is_fresh(fresh, now=now) is True
    assert local_bridge.following_snapshot_is_fresh(stale, now=now) is False
    assert local_bridge.following_snapshot_is_fresh({}, now=now) is False


def test_single_instance_server_disables_address_reuse():
    assert local_bridge.SingleInstanceHTTPServer.allow_reuse_address is False


def get_following_response(state_dir, monkeypatch):
    monkeypatch.setattr(local_bridge, "STATE_DIR", state_dir)
    server = local_bridge.SingleInstanceHTTPServer(
        ("127.0.0.1", 0), local_bridge.Handler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection(*server.server_address, timeout=3)
        connection.request(
            "GET",
            "/api/following",
            headers={"X-Douyin-Archive": local_bridge.EXTENSION_HEADER},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_following_endpoint_forces_old_ui_to_sync_when_cache_is_stale(
    tmp_path, monkeypatch
):
    (tmp_path / "following.json").write_text(
        json.dumps(
            {
                "synced_at": "2026-08-01T00:00:00+00:00",
                "count": 220,
                "authors": [{"sec_uid": "old"}],
            }
        ),
        encoding="utf-8",
    )

    status, payload = get_following_response(tmp_path, monkeypatch)

    assert status == 200
    assert payload == {"ok": True, "count": 0, "authors": [], "stale": True}


def test_following_endpoint_returns_recent_sync_result(tmp_path, monkeypatch):
    (tmp_path / "following.json").write_text(
        json.dumps(
            {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "count": 226,
                "authors": [{"sec_uid": "new"}],
            }
        ),
        encoding="utf-8",
    )

    status, payload = get_following_response(tmp_path, monkeypatch)

    assert status == 200
    assert payload == {
        "ok": True,
        "count": 226,
        "authors": [{"sec_uid": "new"}],
    }


def test_save_browser_cookies_writes_local_auto_config(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    cookie_file = tmp_path / "config" / "cookies.json"
    example = tmp_path / "config.example.yml"
    example.write_text("cookies: {}\n", encoding="utf-8")
    monkeypatch.setattr(local_bridge, "ROOT", tmp_path)
    monkeypatch.setattr(local_bridge, "CONFIG", config)
    monkeypatch.setattr(local_bridge, "COOKIE_FILE", cookie_file)

    count = local_bridge.save_browser_cookies({"sessionid": "secret", "ttwid": "token"})

    assert count == 2
    assert json.loads(cookie_file.read_text(encoding="utf-8"))["sessionid"] == "secret"
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["cookies"] == "auto"


def test_extension_marker_is_accepted_without_origin():
    handler = object.__new__(local_bridge.Handler)
    handler.headers = {
        "X-Douyin-Archive": local_bridge.EXTENSION_HEADER,
        "Origin": "",
    }
    assert handler._origin_allowed() is True


def test_task_state_rejects_a_second_start_while_first_is_starting():
    task = local_bridge.TaskState()
    task.status = "running"

    with pytest.raises(RuntimeError, match="已有任务正在运行"):
        task.start(("download", ["unused"]))


def test_read_douzhencang_author_state(tmp_path):
    appdata = tmp_path / "data" / ".appdata"
    appdata.mkdir(parents=True)
    (appdata / "db_following.js").write_text(
        'window.dbf = String.raw`{"started":["1","2"],'
        '"notInterested":["3"],"authorItems":{"1":{"inFolder":["9"]},'
        '"2":{"inFolder":[]}}}`;',
        encoding="utf-8",
    )
    (appdata / "db_authors.js").write_text(
        'window.dba = String.raw`{"1":{"nicknames":["已有"],"secUid":"sec-1"},'
        '"2":{"nicknames":["新增"],"secUid":"sec-2"},'
        '"3":{"nicknames":["忽略"],"secUid":"sec-3"}}`;',
        encoding="utf-8",
    )

    state = local_bridge.read_douzhencang_author_state(str(tmp_path))

    assert state["available"] is True
    assert state["counts"] == {"library": 1, "pending": 1, "ignored": 1}
    assert {row["state"] for row in state["authors"]} == {
        "library",
        "pending",
        "ignored",
    }


def test_merge_completed_author_state_promotes_and_adds_checked_authors():
    state = {
        "available": True,
        "authors": [
            {
                "uid": "old-pending",
                "sec_uid": "sec-pending",
                "nickname": "待加入",
                "state": "pending",
                "last_checked": 0,
            },
            {
                "uid": "ignored",
                "sec_uid": "sec-ignored",
                "nickname": "不需要",
                "state": "ignored",
                "last_checked": 0,
            },
        ],
        "counts": {"library": 0, "pending": 1, "ignored": 1},
    }

    merged = local_bridge.merge_completed_author_state(
        state,
        {"sec-pending": 123, "sec-new": 456},
        [{"uid": "new", "sec_uid": "sec-new", "nickname": "新作者"}],
    )

    rows = {row["sec_uid"]: row for row in merged["authors"]}
    assert rows["sec-pending"]["state"] == "library"
    assert rows["sec-pending"]["last_checked"] == 123
    assert rows["sec-new"]["state"] == "library"
    assert rows["sec-new"]["nickname"] == "新作者"
    assert merged["counts"] == {"library": 2, "pending": 0, "ignored": 1}


def test_open_local_library_uses_existing_page(tmp_path, monkeypatch):
    page = tmp_path / "本地库.html"
    page.write_text("<html></html>", encoding="utf-8")
    opened = []
    monkeypatch.setattr(os, "startfile", lambda value: opened.append(value), raising=False)

    result = local_bridge.open_local_library(str(tmp_path))

    assert result == str(page)
    assert opened == [str(page)]
