"""Run selected followed authors sequentially and publish structured progress."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class BatchLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                try:
                    owner_pid = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    owner_pid = 0
                if process_is_running(owner_pid):
                    raise RuntimeError("已有关注作者下载任务正在运行")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(str(os.getpid()))
            self.acquired = True
            return self
        raise RuntimeError("无法取得关注作者下载任务锁")

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def count_local_items(database_path: Path, author: Dict[str, Any]) -> int:
    if not database_path.is_file():
        return 0
    uid = str(author.get("uid") or "")
    sec_uid = str(author.get("sec_uid") or "")
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM aweme
            WHERE (? != '' AND author_id = ?)
               OR (? != '' AND author_sec_uid = ?)
            """,
            (uid, uid, sec_uid, sec_uid),
        ).fetchone()
    return int(row[0] if row else 0)


def load_checks(path: Path) -> Dict[str, int]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return {
        str(key): int(value)
        for key, value in payload.items()
        if key and isinstance(value, (int, float))
    }


def make_queue(
    authors: List[Dict[str, Any]],
    database_path: Path,
    checks: Dict[str, int],
) -> List[Dict[str, Any]]:
    queue = []
    for author in authors:
        sec_uid = str(author.get("sec_uid") or "")
        queue.append(
            {
                **author,
                "status": "waiting",
                "last_checked": int(checks.get(sec_uid) or author.get("last_checked") or 0),
                "local_count": count_local_items(database_path, author),
                "downloaded": 0,
                "error": "",
            }
        )
    return queue


def _run_batch(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    base_config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    authors = json.loads(args.authors_file.read_text(encoding="utf-8"))
    if not isinstance(authors, list) or not authors:
        raise RuntimeError("没有待处理作者")

    database_path = Path(
        base_config.get("database_path") or args.state_dir / "following-downloads.db"
    ).resolve()
    checks_path = args.state_dir / "following-checks.json"
    progress_path = args.state_dir / "following-progress.json"
    checks = load_checks(checks_path)
    queue = make_queue(authors, database_path, checks)
    progress = {
        "status": "running",
        "current": 0,
        "total": len(queue),
        "message": "准备开始",
        "authors": queue,
    }
    write_json(progress_path, progress)

    failed = 0
    for index, author in enumerate(queue):
        author["status"] = "downloading"
        progress["current"] = index + 1
        progress["message"] = f"正在打开 @{author.get('nickname') or author.get('unique_id') or author['sec_uid']} 的主页…"
        write_json(progress_path, progress)

        before = int(author["local_count"])
        current_config = dict(base_config)
        browser_fallback = dict(current_config.get("browser_fallback") or {})
        browser_fallback["enabled"] = True
        browser_fallback["headless"] = True
        current_config["browser_fallback"] = browser_fallback
        current_config["link"] = [f"https://www.douyin.com/user/{author['sec_uid']}"]
        current_path = args.state_dir / "following.current.yml"
        current_path.write_text(
            yaml.safe_dump(current_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [sys.executable, str(root / "run.py"), "-c", str(current_path)],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line.rstrip(), flush=True)
        code = process.wait()

        after = count_local_items(database_path, author)
        author["local_count"] = after
        author["downloaded"] = max(0, after - before)
        author["status"] = "completed" if code == 0 else "failed"
        if code:
            failed += 1
            author["error"] = f"下载器退出码 {code}"
        if code == 0:
            checked_at = int(time.time())
            author["last_checked"] = checked_at
            checks[str(author["sec_uid"])] = checked_at
            write_json(checks_path, checks)
        write_json(progress_path, progress)

    progress["status"] = "failed" if failed else "completed"
    progress["message"] = (
        f"完成，{failed} 位作者失败" if failed else f"已完成 {len(queue)} 位作者"
    )
    write_json(progress_path, progress)
    return 1 if failed else 0


def run_batch(args: argparse.Namespace) -> int:
    with BatchLock(args.state_dir / "following-batch.lock"):
        return _run_batch(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="顺序下载关注作者并输出实时进度")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--authors-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run_batch(parse_args()))


if __name__ == "__main__":
    main()
