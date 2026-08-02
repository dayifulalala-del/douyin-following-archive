"""Import downloaded-item IDs from an existing Douzhencang archive."""

import argparse
import asyncio
import base64
import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Set

from storage import Database


def decode_database_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "String.raw" in text:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError(f"无法解析 {path.name}")
        return json.loads(text[start : end + 1])
    first, last = text.find('"'), text.rfind('"')
    if first < 0 or last <= first:
        raise ValueError(f"无法解析 {path.name}")
    raw = gzip.decompress(base64.b64decode(text[first + 1 : last]))
    return json.loads(raw.decode("utf-8"))


def load_optional(appdata: Path, names: Iterable[str]) -> Dict[str, Any]:
    for name in names:
        path = appdata / name
        if path.exists() and path.stat().st_size:
            return decode_database_file(path)
    return {}


def downloaded_ids(
    following: Dict[str, Any],
    likes: Dict[str, Any],
    bookmarked: Dict[str, Any],
) -> Set[str]:
    result: Set[str] = set()
    for author_data in (following.get("authorItems") or {}).values():
        if isinstance(author_data, dict):
            result.update(str(value) for value in (author_data.get("inFolder") or []))
    likes_data = likes.get("likes") if isinstance(likes.get("likes"), dict) else likes
    result.update(str(value) for value in (likes_data.get("downloaded") or []))
    bookmarked_data = (
        bookmarked.get("bookmarked")
        if isinstance(bookmarked.get("bookmarked"), dict)
        else bookmarked
    )
    result.update(str(value) for value in (bookmarked_data.get("downloaded") or []))
    return {value for value in result if value and value.isdigit()}


async def import_archive(archive_dir: Path, database_path: Path) -> int:
    archive_dir = archive_dir.resolve()
    appdata = archive_dir if archive_dir.name == ".appdata" else archive_dir / "data" / ".appdata"
    if not appdata.is_dir():
        raise FileNotFoundError(f"未找到旧数据库目录：{appdata}")

    following = load_optional(appdata, ("db_following.js", "dbf.js"))
    likes = load_optional(appdata, ("db_likes.js", "db.js"))
    bookmarked = load_optional(appdata, ("db_bookmarked.js", "dbb.js"))
    videos = load_optional(appdata, ("db_videos.js", "dbv.js"))
    ids = downloaded_ids(following, likes, bookmarked)
    if not ids:
        raise RuntimeError("旧数据库中没有找到已下载作品记录")

    rows = []
    for aweme_id in sorted(ids):
        video = videos.get(aweme_id) if isinstance(videos.get(aweme_id), dict) else {}
        author = video.get("author") if isinstance(video.get("author"), dict) else {}
        rows.append(
            {
                "aweme_id": aweme_id,
                "aweme_type": "video",
                "title": video.get("desc") or video.get("title") or "抖珍藏旧记录",
                "author_id": str(author.get("uid") or video.get("authorId") or ""),
                "author_name": str(author.get("nickname") or ""),
                "author_sec_uid": str(author.get("sec_uid") or ""),
                "create_time": video.get("create_time") or video.get("createTime") or 0,
                "file_path": f"{archive_dir}#douzhencang:{aweme_id}",
                "metadata": json.dumps(video, ensure_ascii=False) if video else "",
            }
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(str(database_path))
    await database.initialize()
    await database.add_aweme_batch(rows)
    await database.close()
    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入抖珍藏旧库，避免重复下载")
    parser.add_argument("archive_dir", type=Path, help="抖珍藏原归档文件夹")
    parser.add_argument(
        "--database", type=Path, default=Path("state/following-downloads.db")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = asyncio.run(import_archive(args.archive_dir, args.database.resolve()))
    print(f"[完成] 已导入 {count} 条抖珍藏旧下载记录，新工具将自动跳过这些作品。")


if __name__ == "__main__":
    main()
