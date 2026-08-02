"""Sync every creator followed by the logged-in Douyin account."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config import ConfigLoader
from core import DouyinAPIClient


def _first_image_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    urls = value.get("url_list") or value.get("urlList") or []
    if isinstance(urls, list) and urls:
        return str(urls[0] or "")
    return str(value.get("uri") or "")


def normalize_author(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user = item.get("user") if isinstance(item.get("user"), dict) else item
    sec_uid = str(user.get("sec_uid") or user.get("secUid") or "").strip()
    if not sec_uid:
        return None
    avatar_url = ""
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger", "avatar"):
        avatar_url = _first_image_url(user.get(key))
        if avatar_url:
            break
    return {
        "sec_uid": sec_uid,
        "uid": str(user.get("uid") or ""),
        "nickname": str(user.get("nickname") or ""),
        "unique_id": str(user.get("unique_id") or user.get("uniqueId") or ""),
        "signature": str(user.get("signature") or ""),
        "avatar_url": avatar_url,
        "aweme_count": int(user.get("aweme_count") or user.get("video_count") or 0),
        "url": f"https://www.douyin.com/user/{sec_uid}",
    }


async def collect_following(
    api_client: Any,
    sec_uid: str,
    *,
    max_pages: int = 500,
    delay_seconds: float = 0.55,
) -> List[Dict[str, Any]]:
    authors: Dict[str, Dict[str, Any]] = {}
    max_time = 0
    seen_cursors = set()

    for page_number in range(1, max_pages + 1):
        page = await api_client.get_following_page(sec_uid, max_time=max_time, count=20)
        items = page.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            author = normalize_author(item)
            if author:
                authors[author["sec_uid"]] = author

        print(f"[同步] 第 {page_number} 页，本页 {len(items)} 人，累计 {len(authors)} 人")
        next_cursor = int(page.get("min_time") or 0)
        has_more = bool(page.get("has_more"))
        if not has_more or not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        max_time = next_cursor
        if delay_seconds:
            await asyncio.sleep(delay_seconds)

    return list(authors.values())


def write_outputs(
    *,
    base_config_path: Path,
    state_dir: Path,
    download_dir: Path,
    self_info: Dict[str, Any],
    authors: List[Dict[str, Any]],
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "sec_uid": self_info.get("sec_uid") or self_info.get("secUid") or "",
            "nickname": self_info.get("nickname") or "",
        },
        "count": len(authors),
        "authors": authors,
    }
    (state_dir / "following.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (state_dir / "following-links.txt").write_text(
        "\n".join(author["url"] for author in authors) + "\n", encoding="utf-8"
    )

    config_data = yaml.safe_load(base_config_path.read_text(encoding="utf-8")) or {}
    config_data["link"] = [author["url"] for author in authors]
    config_data["path"] = str(download_dir.resolve())
    config_data["mode"] = ["post"]
    config_data.setdefault("number", {})["post"] = 0
    config_data.setdefault("increase", {})["post"] = True
    config_data["database"] = True
    config_data["database_path"] = str((state_dir / "following-downloads.db").resolve())
    config_data["author_dir"] = "nickname_uid"
    config_data["thread"] = min(int(config_data.get("thread") or 3), 3)
    config_data["rate_limit"] = min(float(config_data.get("rate_limit") or 2), 2)
    browser_fallback = config_data.setdefault("browser_fallback", {})
    browser_fallback["enabled"] = True
    browser_fallback["headless"] = True

    generated = state_dir / "following.config.yml"
    generated.write_text(
        yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return generated


async def sync(args: argparse.Namespace) -> int:
    config_path = args.config.resolve()
    config = ConfigLoader(str(config_path))
    cookies = config.get_cookies()
    if not cookies or any(str(value).startswith("YOUR_") for value in cookies.values()):
        raise RuntimeError("尚未登录。请先运行“登录/更新登录”。")

    async with DouyinAPIClient(cookies, proxy=config.get("proxy")) as api_client:
        self_info = await api_client.get_self_info()
        if not self_info:
            raise RuntimeError("无法读取当前抖音账号，请重新登录后再试。")
        sec_uid = str(self_info.get("sec_uid") or self_info.get("secUid") or "")
        if not sec_uid:
            raise RuntimeError("当前账号响应中没有 sec_uid。")
        authors = await collect_following(
            api_client,
            sec_uid,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
        )

    if not authors:
        raise RuntimeError("没有同步到关注作者；请检查登录状态或稍后重试。")
    generated = write_outputs(
        base_config_path=config_path,
        state_dir=args.state_dir.resolve(),
        download_dir=args.download_dir.resolve(),
        self_info=self_info,
        authors=authors,
    )
    print(f"[完成] 已同步 {len(authors)} 位作者")
    print(f"[完成] 下载配置：{generated}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步登录账号的全部关注作者")
    parser.add_argument("--config", type=Path, default=Path("config.yml"))
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--download-dir", type=Path, default=Path("Downloaded-Following"))
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.55)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(sync(parse_args())))


if __name__ == "__main__":
    main()
