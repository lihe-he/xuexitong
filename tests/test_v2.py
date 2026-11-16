"""v0.2 新增能力的测试：加密、令牌桶、退避、Cookie 解析、二维码解码。"""

from __future__ import annotations

import time

import pytest

from cxsign import qrdecode
from cxsign.course import parse_cookies
from cxsign.ratelimit import NullBucket, TokenBucket
from cxsign.security import PREFIX, SecretBox, SecretError, mask


# ---------------------------------------------------------------- security
def test_secretbox_roundtrip(tmp_path):
    box = SecretBox.load(tmp_path)
    token = box.encrypt("MyP@ssw0rd")
    assert token.startswith(PREFIX)
    assert "MyP@ssw0rd" not in token
    assert box.decrypt(token) == "MyP@ssw0rd"


def test_secretbox_stable_across_instances(tmp_path):
    a = SecretBox.load(tmp_path)
    token = a.encrypt("hello")
    b = SecretBox.load(tmp_path)          # 复用同一个 key 文件
    assert b.decrypt(token) == "hello"


def test_secretbox_plaintext_passthrough(tmp_path):
    """历史明文数据要能读，不能因为上线加密就打不开库。"""
    box = SecretBox.load(tmp_path)
    assert box.decrypt("legacy-plain-password") == "legacy-plain-password"


def test_secretbox_empty(tmp_path):
    box = SecretBox.load(tmp_path)
    assert box.encrypt("") == ""
    assert box.decrypt("") == ""


def test_secretbox_wrong_key_raises(tmp_path, monkeypatch):
    box1 = SecretBox.load(tmp_path / "a")
    token = box1.encrypt("secret")
    box2 = SecretBox.load(tmp_path / "b")
    with pytest.raises(SecretError):
        box2.decrypt(token)


def test_secretbox_env_key(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CXSIGN_SECRET", key)
    box = SecretBox.load(tmp_path)
    assert box.source.startswith("env:")
    assert box.decrypt(box.encrypt("x")) == "x"


def test_is_encrypted():
    assert SecretBox.is_encrypted(PREFIX + "abc")
    assert not SecretBox.is_encrypted("plain")
    assert not SecretBox.is_encrypted("")


def test_mask():
    assert mask("") == ""
    assert mask("ab") == "**"
    assert mask("MyPassword", keep=2) == "My******rd"


# ------------------------------------------------------------- ratelimit
def test_token_bucket_consumes():
    bucket = TokenBucket(rate=1000, burst=2)
    assert bucket.acquire()
    assert bucket.acquire()
    assert bucket.available < 1


def test_token_bucket_refills():
    bucket = TokenBucket(rate=100, burst=1)
    bucket.acquire()
    time.sleep(0.05)
    assert bucket.acquire(timeout=0.5)


def test_token_bucket_timeout():
    bucket = TokenBucket(rate=0.1, burst=1)
    bucket.acquire()
    started = time.monotonic()
    assert bucket.acquire(timeout=0.05) is False
    assert time.monotonic() - started < 0.5


def test_null_bucket():
    assert NullBucket().acquire()
    assert NullBucket().available == float("inf")


# --------------------------------------------------------------- cookies
def test_parse_cookies_header_style():
    got = parse_cookies("_uid=123; fid=456; _d=abc; vc3=zzz")
    assert got["_uid"] == "123"
    assert got["fid"] == "456"
    assert set(got) == {"_uid", "fid", "_d", "vc3"}


def test_parse_cookies_strips_prefix():
    got = parse_cookies("Cookie: _uid=1; fid=2")
    assert got == {"_uid": "1", "fid": "2"}


def test_parse_cookies_json():
    got = parse_cookies('{"_uid":"1","fid":"2"}')
    assert got == {"_uid": "1", "fid": "2"}


def test_parse_cookies_dict():
    assert parse_cookies({"_uid": "1", "fid": "2"}) == {"_uid": "1", "fid": "2"}


def test_parse_cookies_drops_noise():
    got = parse_cookies("_uid=1; t=true; _blank=1; refer=xx; fid=2")
    assert set(got) == {"_uid", "fid"}


def test_parse_cookies_multiline():
    got = parse_cookies("_uid=1;\nfid=2;\n_d=3")
    assert got == {"_uid": "1", "fid": "2", "_d": "3"}


def test_parse_cookies_empty():
    assert parse_cookies("") == {}
    assert parse_cookies("garbage") == {}


# ------------------------------------------------------------- qr decode
def test_qrdecode_available_is_bool():
    assert isinstance(qrdecode.available(), bool)


def test_qrdecode_empty_input_raises():
    with pytest.raises(qrdecode.QrDecodeError):
        qrdecode.decode_enc(b"")


def test_qrdecode_reports_missing_dependency():
    if qrdecode.available():
        pytest.skip("opencv 已安装，跳过缺失分支")
    with pytest.raises(qrdecode.QrDecodeError) as exc:
        qrdecode.decode_enc(b"\x89PNG dummy")
    assert "opencv" in str(exc.value)


def test_qrdecode_roundtrip():
    """真造一张二维码再解回来，端到端验证 enc 提取。"""
    if not qrdecode.available():
        pytest.skip("未安装 opencv")

    import cv2

    payload = (
        "http://mobilelearn.chaoxing.com/newsign/index"
        "?enc=1D0A628CK317F44CCC378M5KD92&x=1"
    )
    code = cv2.QRCodeEncoder.create().encode(payload)
    code = cv2.resize(code, (400, 400), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", code)
    assert ok

    data = buf.tobytes()
    assert qrdecode.decode_text(data) == payload
    assert qrdecode.decode_enc(data) == "1D0A628CK317F44CCC378M5KD92"


def test_qrdecode_rejects_non_chaoxing_qr():
    if not qrdecode.available():
        pytest.skip("未安装 opencv")

    import cv2

    code = cv2.QRCodeEncoder.create().encode("https://example.com/hello")
    code = cv2.resize(code, (300, 300), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", code)
    assert ok

    with pytest.raises(qrdecode.QrDecodeError):
        qrdecode.decode_enc(buf.tobytes())
