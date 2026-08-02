import argparse
import json
import sqlite3

import pytest
import yaml

from tools import following_batch
from tools.following_batch import make_queue


def test_make_queue_reports_real_local_count_and_last_check(tmp_path):
    database = tmp_path / "downloads.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE aweme (author_id TEXT, author_sec_uid TEXT)"
        )
        connection.executemany(
            "INSERT INTO aweme VALUES (?, ?)",
            [("uid-1", "sec-1"), ("uid-1", "sec-1"), ("other", "other-sec")],
        )

    queue = make_queue(
        [
            {
                "uid": "uid-1",
                "sec_uid": "sec-1",
                "nickname": "作者",
                "avatar_url": "https://example.com/a.jpg",
            }
        ],
        database,
        {"sec-1": 123},
    )

    assert queue[0]["status"] == "waiting"
    assert queue[0]["local_count"] == 2
    assert queue[0]["last_checked"] == 123


def test_run_batch_publishes_completed_author_progress(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    config.write_text(
        yaml.safe_dump({"database_path": str(tmp_path / "downloads.db")}),
        encoding="utf-8",
    )
    authors_file = tmp_path / "authors.json"
    authors_file.write_text(
        json.dumps(
            [
                {
                    "uid": "uid-1",
                    "sec_uid": "sec-1",
                    "nickname": "作者",
                    "aweme_count": 8,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    counts = iter((2, 4))
    monkeypatch.setattr(
        following_batch, "count_local_items", lambda *_args: next(counts)
    )

    class FakeProcess:
        stdout = ["模拟下载\n"]

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(
        following_batch.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess()
    )
    args = argparse.Namespace(
        config=config,
        authors_file=authors_file,
        state_dir=tmp_path / "state",
    )

    assert following_batch.run_batch(args) == 0
    progress = json.loads(
        (args.state_dir / "following-progress.json").read_text(encoding="utf-8")
    )
    assert progress["status"] == "completed"
    assert progress["authors"][0]["status"] == "completed"
    assert progress["authors"][0]["downloaded"] == 2
    generated = yaml.safe_load(
        (args.state_dir / "following.current.yml").read_text(encoding="utf-8")
    )
    assert generated["browser_fallback"] == {"enabled": True, "headless": True}


def test_batch_lock_rejects_a_second_running_batch(tmp_path, monkeypatch):
    lock_path = tmp_path / "following-batch.lock"
    monkeypatch.setattr(following_batch, "process_is_running", lambda _pid: True)
    lock_path.write_text("123", encoding="ascii")

    with pytest.raises(RuntimeError, match="已有关注作者下载任务正在运行"):
        with following_batch.BatchLock(lock_path):
            pass


def test_failed_author_is_not_marked_as_recently_checked(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    config.write_text(
        yaml.safe_dump({"database_path": str(tmp_path / "downloads.db")}),
        encoding="utf-8",
    )
    authors_file = tmp_path / "authors.json"
    authors_file.write_text(
        json.dumps([{"uid": "uid-1", "sec_uid": "sec-1"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(following_batch, "count_local_items", lambda *_args: 0)

    class FailedProcess:
        stdout = []

        @staticmethod
        def wait():
            return 1

    monkeypatch.setattr(
        following_batch.subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess()
    )
    args = argparse.Namespace(
        config=config,
        authors_file=authors_file,
        state_dir=tmp_path / "state",
    )

    assert following_batch.run_batch(args) == 1
    assert not (args.state_dir / "following-checks.json").exists()
