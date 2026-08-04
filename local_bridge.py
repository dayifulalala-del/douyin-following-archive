"""Local-only HTTP bridge for the Chrome extension."""

import json
import os
import socket
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

import yaml

from tools.import_douzhencang import load_optional
from utils.cookie_utils import sanitize_cookies

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yml"
STATE_DIR = ROOT / "state"
COOKIE_FILE = ROOT / "config" / "cookies.json"
HOST = "127.0.0.1"
PORT = 8766
EXTENSION_HEADER = "douyin-archive-extension-v1"
FOLLOWING_CACHE_MAX_AGE_SECONDS = 300


def following_snapshot_is_fresh(
    payload: Dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: int = FOLLOWING_CACHE_MAX_AGE_SECONDS,
) -> bool:
    synced_at = str(payload.get("synced_at") or "").strip()
    if not synced_at:
        return False
    try:
        synced = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return 0 <= (current - synced).total_seconds() <= max_age_seconds


def task_error_message(logs: List[str]) -> str:
    """Return a useful task error instead of a late buffered progress line."""
    lines = [str(line).strip() for line in logs if str(line).strip()]
    joined = "\n".join(lines).lower()
    if "empty 200 response" in joined or "anti-bot" in joined:
        return "抖音暂时拦截了关注列表刷新，请稍后重试。"
    for line in reversed(lines):
        if "RuntimeError:" in line:
            return line.split("RuntimeError:", 1)[1].strip()
        if line.startswith("[失败]"):
            return line[len("[失败]") :].strip() or "任务失败，请稍后重试。"
    return "任务失败，请稍后重试。"


def read_following_snapshot(*, include_stale: bool = False) -> Dict[str, Any]:
    """Read the last successful snapshot, optionally including an old cache."""
    snapshot_file = STATE_DIR / "following.json"
    if not snapshot_file.exists():
        return {"ok": True, "count": 0, "authors": []}
    try:
        payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"ok": True, "count": 0, "authors": []}

    authors = payload.get("authors") or []
    if not isinstance(authors, list):
        authors = []
    stale = not following_snapshot_is_fresh(payload)
    if stale and not include_stale:
        return {"ok": True, "count": 0, "authors": [], "stale": True}
    result = {
        "ok": True,
        "count": int(payload.get("count") or len(authors)),
        "authors": authors,
    }
    if stale:
        result["stale"] = True
    return result


class TaskState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process = None
        self.kind = ""
        self.status = "idle"
        self.exit_code = None
        self.logs = deque(maxlen=300)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            count = 0
            snapshot_file = STATE_DIR / "following.json"
            if snapshot_file.exists():
                try:
                    count = int(json.loads(snapshot_file.read_text(encoding="utf-8")).get("count", 0))
                except (OSError, ValueError, TypeError):
                    count = 0
            payload = {
                "kind": self.kind,
                "status": self.status,
                "exit_code": self.exit_code,
                "following_count": count,
                "logs": list(self.logs),
            }
            if self.status == "failed":
                payload["error"] = task_error_message(list(self.logs))
            progress_file = STATE_DIR / "following-progress.json"
            if progress_file.exists():
                try:
                    payload["download_progress"] = json.loads(
                        progress_file.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError, TypeError):
                    payload["download_progress"] = {}
            return payload

    def start(self, command) -> None:
        with self.lock:
            if self.status == "running" or (
                self.process and self.process.poll() is None
            ):
                raise RuntimeError("已有任务正在运行")
            self.kind = command[0]
            self.status = "running"
            self.exit_code = None
            self.logs.clear()

        def worker() -> None:
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONUNBUFFERED"] = "1"
            try:
                process = subprocess.Popen(
                    command[1],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=child_env,
                )
            except Exception as exc:
                with self.lock:
                    self.status = "failed"
                    self.exit_code = -1
                    self.logs.append(str(exc))
                return
            with self.lock:
                self.process = process
            assert process.stdout is not None
            for line in process.stdout:
                with self.lock:
                    self.logs.append(line.rstrip())
            code = process.wait()
            with self.lock:
                self.exit_code = code
                self.status = "completed" if code == 0 else "failed"
                self.process = None

        threading.Thread(target=worker, daemon=True).start()

    def stop(self) -> None:
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                process.terminate()


TASK = TaskState()


class SingleInstanceHTTPServer(ThreadingHTTPServer):
    """Refuse a second bridge process from sharing the same local port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def save_browser_cookies(raw: Dict[str, Any], user_agent: str = "") -> int:
    cookies = sanitize_cookies({str(key): str(value) for key, value in raw.items()})
    if not cookies:
        raise ValueError("没有收到抖音 Cookie")
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

    if not CONFIG.exists():
        CONFIG.write_text((ROOT / "config.example.yml").read_text(encoding="utf-8"), encoding="utf-8")
    config_data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    config_data["cookies"] = "auto"
    normalized_user_agent = " ".join(str(user_agent or "").split())[:512]
    if normalized_user_agent:
        config_data["browser_user_agent"] = normalized_user_agent
    CONFIG.write_text(
        yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return len(cookies)


def read_douzhencang_author_state(archive_dir: str) -> Dict[str, Any]:
    """Read the original archive's author groups without changing its files."""
    archive = Path(archive_dir).expanduser().resolve()
    appdata = archive / "data" / ".appdata"
    if not appdata.is_dir():
        return {"available": False, "authors": [], "counts": {}}

    following = load_optional(appdata, ("db_following.js", "dbf.js"))
    author_db = load_optional(appdata, ("db_authors.js", "dba.js"))
    items = following.get("authorItems") or {}
    last_runs = following.get("lastRun") or {}
    started = {str(value) for value in (following.get("started") or [])}
    ignored = {str(value) for value in (following.get("notInterested") or [])}
    library = {
        str(uid)
        for uid, value in items.items()
        if isinstance(value, dict) and value.get("inFolder")
    }
    pending = started - library

    def author_payload(uid: str, state: str) -> Dict[str, str]:
        value = author_db.get(uid) if isinstance(author_db.get(uid), dict) else {}
        nicknames = value.get("nicknames") or []
        nickname = str(nicknames[-1]) if isinstance(nicknames, list) and nicknames else ""
        run = last_runs.get(uid) if isinstance(last_runs.get(uid), dict) else {}
        return {
            "uid": uid,
            "sec_uid": str(value.get("secUid") or value.get("sec_uid") or ""),
            "nickname": nickname,
            "state": state,
            "last_checked": int((run.get("finish") or 0) / 1000),
        }

    rows = [author_payload(uid, "library") for uid in sorted(library)]
    rows.extend(author_payload(uid, "pending") for uid in sorted(pending))
    rows.extend(author_payload(uid, "ignored") for uid in sorted(ignored))
    return {
        "available": True,
        "authors": rows,
        "counts": {
            "library": len(library),
            "pending": len(pending),
            "ignored": len(ignored),
        },
    }


def merge_completed_author_state(
    state: Dict[str, Any],
    checks: Dict[str, Any],
    current_authors: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Promote successfully checked authors into the local-library group."""
    rows = [dict(author) for author in (state.get("authors") or [])]
    by_sec_uid = {
        str(author.get("sec_uid") or ""): author
        for author in rows
        if author.get("sec_uid")
    }
    current_by_sec_uid = {
        str(author.get("sec_uid") or ""): author
        for author in current_authors
        if author.get("sec_uid")
    }

    for sec_uid, checked_at in checks.items():
        sec_uid = str(sec_uid or "")
        checked_at = int(checked_at or 0)
        if not sec_uid or checked_at <= 0:
            continue
        author = by_sec_uid.get(sec_uid)
        if author is None:
            current = current_by_sec_uid.get(sec_uid, {})
            author = {
                "uid": str(current.get("uid") or ""),
                "sec_uid": sec_uid,
                "nickname": str(current.get("nickname") or ""),
                "state": "library",
                "last_checked": checked_at,
            }
            rows.append(author)
            by_sec_uid[sec_uid] = author
        else:
            author["state"] = "library"
            author["last_checked"] = max(
                int(author.get("last_checked") or 0),
                checked_at,
            )

    counts = {"library": 0, "pending": 0, "ignored": 0}
    for author in rows:
        state_name = str(author.get("state") or "pending")
        if state_name in counts:
            counts[state_name] += 1
    return {**state, "authors": rows, "counts": counts}


def open_local_library(archive_dir: str) -> str:
    archive = Path(archive_dir).expanduser().resolve()
    library = archive / "本地库.html"
    if not library.is_file():
        raise FileNotFoundError("所选文件夹中没有“本地库.html”")
    os.startfile(str(library))
    return str(library)


class Handler(BaseHTTPRequestHandler):
    server_version = "DouyinArchiveBridge/1.0"

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        marker = self.headers.get("X-Douyin-Archive", "")
        return origin.startswith("chrome-extension://") or marker == EXTENSION_HEADER

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Douyin-Archive")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if not self._origin_allowed():
            self._send(403, {"ok": False, "error": "仅允许浏览器扩展访问"})
            return
        if self.path == "/api/health":
            self._send(200, {"ok": True, "service": "douyin-following-archive"})
        elif self.path == "/api/status":
            self._send(200, {"ok": True, **TASK.snapshot()})
        elif self.path == "/api/following":
            self._send(200, read_following_snapshot())
        elif self.path == "/api/following-cached":
            self._send(200, read_following_snapshot(include_stale=True))
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._origin_allowed():
            self._send(403, {"ok": False, "error": "仅允许浏览器扩展访问"})
            return
        try:
            body = self._body()
            if self.path == "/api/cookies":
                count = save_browser_cookies(
                    body.get("cookies") or {},
                    str(body.get("user_agent") or ""),
                )
                self._send(200, {"ok": True, "cookie_count": count})
            elif self.path == "/api/select-folder":
                selected = select_native_folder(str(body.get("initial_dir") or ""))
                self._send(200, {"ok": True, "path": selected})
            elif self.path == "/api/archive-authors":
                archive_dir = str(body.get("archive_dir") or "").strip()
                state = read_douzhencang_author_state(archive_dir)
                checks_file = STATE_DIR / "following-checks.json"
                checks = {}
                if checks_file.exists():
                    checks = json.loads(checks_file.read_text(encoding="utf-8"))
                snapshot_file = STATE_DIR / "following.json"
                current_authors = []
                if snapshot_file.exists():
                    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
                    current_authors = snapshot.get("authors") or []
                state = merge_completed_author_state(state, checks, current_authors)
                self._send(200, {"ok": True, **state, "checks": checks})
            elif self.path == "/api/open-library":
                archive_dir = str(body.get("archive_dir") or "").strip()
                if not archive_dir:
                    raise RuntimeError("请先指定目标文件夹")
                path = open_local_library(archive_dir)
                self._send(200, {"ok": True, "path": path})
            elif self.path == "/api/sync":
                download_dir = body.get("download_dir") or str(ROOT / "Downloaded-Following")
                TASK.start(
                    (
                        "sync",
                        [
                            sys.executable,
                            "-m",
                            "tools.following_sync",
                            "--config",
                            str(CONFIG),
                            "--state-dir",
                            str(STATE_DIR),
                            "--download-dir",
                            str(download_dir),
                        ],
                    )
                )
                self._send(202, {"ok": True})
            elif self.path == "/api/download":
                generated = STATE_DIR / "following.config.yml"
                if not generated.exists():
                    raise RuntimeError("请先同步关注列表")
                selected = {
                    str(value) for value in (body.get("selected_sec_uids") or []) if value
                }
                if not selected:
                    raise RuntimeError("没有选中任何作者")
                snapshot_file = STATE_DIR / "following.json"
                snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
                chosen_authors = [
                    author
                    for author in (snapshot.get("authors") or [])
                    if str(author.get("sec_uid") or "") in selected
                ]
                if not chosen_authors:
                    raise RuntimeError("没有找到所选作者")
                authors_file = STATE_DIR / "following.selected-authors.json"
                authors_file.write_text(
                    json.dumps(chosen_authors, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                TASK.start(
                    (
                        "download",
                        [
                            sys.executable,
                            "-m",
                            "tools.following_batch",
                            "--config",
                            str(generated),
                            "--authors-file",
                            str(authors_file),
                            "--state-dir",
                            str(STATE_DIR),
                        ],
                    )
                )
                self._send(202, {"ok": True, "authors": chosen_authors})
            elif self.path == "/api/account-download":
                mode = str(body.get("mode") or "")
                if mode not in {"like", "collect"}:
                    raise RuntimeError("不支持的下载类型")
                TASK.start(
                    (
                        mode,
                        [
                            sys.executable,
                            "-m",
                            "tools.download_account",
                            mode,
                            "--config",
                            str(CONFIG),
                            "--state-dir",
                            str(STATE_DIR),
                            "--download-dir",
                            str(body.get("download_dir") or ROOT / "Downloaded-Account"),
                        ],
                    )
                )
                self._send(202, {"ok": True})
            elif self.path == "/api/import-douzhencang":
                archive_dir = str(body.get("archive_dir") or "").strip()
                if not archive_dir:
                    raise RuntimeError("请输入抖珍藏原归档文件夹路径")
                TASK.start(
                    (
                        "import",
                        [
                            sys.executable,
                            "-m",
                            "tools.import_douzhencang",
                            archive_dir,
                            "--database",
                            str(STATE_DIR / "following-downloads.db"),
                        ],
                    )
                )
                self._send(202, {"ok": True})
            elif self.path == "/api/stop":
                TASK.stop()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self._send(400, {"ok": False, "error": str(exc)})

    def log_message(self, _format, *_args) -> None:
        return


def select_native_folder(initial_dir: str = "") -> str:
    """Show the real Windows directory picker and return the chosen path."""
    import tkinter as tk
    from tkinter import filedialog

    initial = Path(initial_dir).expanduser()
    kwargs: Dict[str, Any] = {"title": "选择抖音视频保存文件夹", "mustexist": True}
    if initial.is_dir():
        kwargs["initialdir"] = str(initial)
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        return str(filedialog.askdirectory(parent=root, **kwargs) or "")
    finally:
        root.destroy()


def main() -> None:
    print(f"抖音关注珍藏本机服务已启动：http://{HOST}:{PORT}")
    print("请保持本窗口打开，然后使用 Chrome 扩展。")
    SingleInstanceHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
