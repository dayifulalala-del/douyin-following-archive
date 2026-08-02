from argparse import Namespace

import pytest
import yaml

import tools.download_account as download_account


class FakeClient:
    def __init__(self, _cookies, proxy=None):
        self.proxy = proxy

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_self_info(self):
        return {"sec_uid": "self-sec", "nickname": "测试账号"}


@pytest.mark.parametrize(
    ("mode", "expected_mode", "expected_link"),
    [
        ("like", "like", "https://www.douyin.com/user/self-sec"),
        (
            "collect",
            "collect",
            "https://www.douyin.com/user/self?showTab=favorite_collection",
        ),
    ],
)
async def test_prepare_account_download_config(
    tmp_path, monkeypatch, mode, expected_mode, expected_link
):
    config = tmp_path / "config.yml"
    config.write_text(
        yaml.safe_dump({"cookies": {"sessionid": "x"}, "number": {}, "increase": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(download_account, "DouyinAPIClient", FakeClient)
    args = Namespace(
        mode=mode,
        config=config,
        state_dir=tmp_path / "state",
        download_dir=tmp_path / "downloads",
    )

    generated = await download_account.prepare(args)
    data = yaml.safe_load(generated.read_text(encoding="utf-8"))

    assert data["mode"] == [expected_mode]
    assert data["link"] == [expected_link]
    assert data["number"][expected_mode] == 0
