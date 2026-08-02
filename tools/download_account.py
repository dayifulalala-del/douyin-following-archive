"""Prepare and run an unlimited logged-in account download."""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import yaml

from config import ConfigLoader
from core import DouyinAPIClient


async def prepare(args: argparse.Namespace) -> Path:
    config = ConfigLoader(str(args.config))
    cookies = config.get_cookies()
    if not cookies:
        raise RuntimeError("请先同步当前 Chrome 登录")
    async with DouyinAPIClient(cookies, proxy=config.get("proxy")) as api_client:
        self_info = await api_client.get_self_info()
    if not self_info:
        raise RuntimeError("无法读取当前抖音账号，请重新登录")

    data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    args.state_dir.mkdir(parents=True, exist_ok=True)
    data["path"] = str(args.download_dir.resolve())
    data["database"] = True
    data["database_path"] = str((args.state_dir / "following-downloads.db").resolve())
    if args.mode == "like":
        sec_uid = str(self_info.get("sec_uid") or self_info.get("secUid") or "")
        data["link"] = [f"https://www.douyin.com/user/{sec_uid}"]
        data["mode"] = ["like"]
        data.setdefault("number", {})["like"] = 0
        data.setdefault("increase", {})["like"] = True
    else:
        data["link"] = ["https://www.douyin.com/user/self?showTab=favorite_collection"]
        data["mode"] = ["collect"]
        data.setdefault("number", {})["collect"] = 0

    generated = args.state_dir / f"account-{args.mode}.yml"
    generated.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["like", "collect"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated = asyncio.run(prepare(args))
    raise SystemExit(
        subprocess.call([sys.executable, str(Path(__file__).parents[1] / "run.py"), "-c", str(generated)])
    )


if __name__ == "__main__":
    main()
