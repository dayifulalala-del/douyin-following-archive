import base64
import gzip
import json

from tools.import_douzhencang import decode_database_file, downloaded_ids


def test_decode_plain_and_compressed_database_files(tmp_path):
    payload = {"authorItems": {"u1": {"inFolder": ["11", "12"]}}}
    plain = tmp_path / "db_following.js"
    plain.write_text(
        "window.dbf=String.raw`" + json.dumps(payload) + "`;", encoding="utf-8"
    )
    assert decode_database_file(plain) == payload

    compressed = tmp_path / "dbf.js"
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()
    compressed.write_text(f'window.dbf_base64="{encoded}";', encoding="utf-8")
    assert decode_database_file(compressed) == payload


def test_downloaded_ids_combines_following_likes_and_bookmarks():
    result = downloaded_ids(
        {"authorItems": {"u": {"inFolder": ["11", "12"]}}},
        {"likes": {"downloaded": ["12", "13"]}},
        {"downloaded": ["14", "not-an-id"]},
    )
    assert result == {"11", "12", "13", "14"}
