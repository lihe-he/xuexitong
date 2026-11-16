"""单元测试：只测纯逻辑，不联网。"""

from __future__ import annotations

import base64

import pytest

from cxsign.activity import SignKind, classify
from cxsign.course import parse_course_json
from cxsign.crypto import aes_encrypt, des_encrypt, encrypt_password
from cxsign.signer.base import parse_reply
from cxsign.signer.location import jitter, location_distance
from cxsign.signer.qrcode import build_location_payload, extract_enc


# ------------------------------------------------------------------ crypto
def test_aes_is_base64_and_stable():
    out = aes_encrypt("hello")
    assert isinstance(out, str)
    raw = base64.b64decode(out)
    assert len(raw) % 16 == 0
    # 同输入同输出（固定 key/iv）
    assert aes_encrypt("hello") == out


def test_aes_padding_block():
    # 16 字节输入要补出完整一个块
    assert len(base64.b64decode(aes_encrypt("0123456789abcdef"))) == 32


def test_des_hex_uppercase():
    out = des_encrypt("hello")
    assert out == out.upper()
    assert len(out) % 16 == 0


def test_encrypt_password_dispatch():
    assert encrypt_password("x", "aes") == aes_encrypt("x")
    assert encrypt_password("x", "des") == des_encrypt("x")


# ---------------------------------------------------------------- classify
@pytest.mark.parametrize(
    ("info", "expect"),
    [
        ({"otherId": 0, "ifphoto": 0}, SignKind.PLAIN),
        ({"otherId": 0, "ifphoto": 1}, SignKind.PHOTO),
        ({"otherId": 0}, SignKind.PLAIN),
        ({"otherId": 2}, SignKind.QRCODE),
        ({"otherId": 3}, SignKind.GESTURE),
        ({"otherId": 4}, SignKind.LOCATION),
        ({"otherId": 5}, SignKind.SIGNCODE),
        ({"otherId": 99, "activeSort": 5}, SignKind.FACE),
        ({"otherId": 99, "activeSort": 9}, SignKind.SIGNCODE),
        ({"otherId": 99, "activeSort": 7}, SignKind.QRCODE),
        ({"otherId": 99}, SignKind.UNKNOWN),
        ({}, SignKind.UNKNOWN),
        ({"otherId": "4"}, SignKind.LOCATION),
        ({"otherId": "abc"}, SignKind.UNKNOWN),
    ],
)
def test_classify(info, expect):
    assert classify(info) is expect


def test_ifphoto_overrides_other_id_zero():
    """新手最常翻车的点：otherId=0 也可能是拍照签到。"""
    assert classify({"otherId": 0, "ifphoto": "1"}) is SignKind.PHOTO


# ------------------------------------------------------------------- reply
@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("success", True),
        ("success2", True),
        (" SUCCESS ", True),
        ("fail", False),
        ("", False),
        ("签到失败，请重新扫描", False),
        ("您已经签到过了", False),
        ("距离签到位置 1234 米", False),
    ],
)
def test_parse_reply(text, ok):
    got_ok, msg = parse_reply(text)
    assert got_ok is ok
    assert msg


def test_parse_reply_distance_kept():
    ok, msg = parse_reply("距离签到位置 512 米")
    assert not ok
    assert "512" in msg


# -------------------------------------------------------------------
def test_extract_enc_from_url():
    url = "http://mobilelearn.chaoxing.com/newsign/xxx?enc=1D0A628CK317F44CCC378M5KD92&x=1"
    assert extract_enc(url) == "1D0A628CK317F44CCC378M5KD92"


def test_extract_enc_bare():
    assert extract_enc("1D0A628CK317F44CCC378M5KD92") == "1D0A628CK317F44CCC378M5KD92"


def test_extract_enc_empty():
    assert extract_enc("") == ""


def test_build_location_payload():
    payload = build_location_payload("34.817038", "113.516288", "河南省郑州市")
    assert '"result":"1"' in payload
    assert "34.817038" in payload
    assert "河南省郑州市" in payload


# ----------------------------------------------------------------- jitter
def test_jitter_within_radius():
    for _ in range(50):
        lat, lon = jitter(34.0, 113.0, 10.0)
        assert abs(float(lat) - 34.0) < 0.001
        assert abs(float(lon) - 113.0) < 0.001


def test_jitter_zero_radius_keeps_point():
    assert jitter(34.0, 113.0, 0.0) == ("34.000000", "113.000000")


def test_jitter_varies():
    points = {jitter(34.0, 113.0, 20.0) for _ in range(20)}
    assert len(points) > 15


def test_location_distance():
    assert location_distance("距离签到位置 1234 米") == 1234
    assert location_distance("距离签到位置 12.7 米") == 12
    assert location_distance("success") is None


# ----------------------------------------------------------------- course
def test_parse_course_json():
    text = '[{"courseid":"241234567","clazzid":"123456"}]'
    courses = parse_course_json(text)
    assert len(courses) == 1
    assert courses[0].course_id == "241234567"
    assert courses[0].class_id == "123456"
