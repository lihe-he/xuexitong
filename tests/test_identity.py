"""身份隔离层测试。"""

from __future__ import annotations

from cxsign.identity import UA_POOL, Identity, build, make_device_code, pick_proxy, pick_ua


def test_device_code_is_32_hex_and_stable():
    a = make_device_code("1:13800000001")
    b = make_device_code("1:13800000001")
    assert a == b
    assert len(a) == 32
    int(a, 16)  # 必须是合法 hex


def test_device_code_differs_per_account():
    codes = {make_device_code(f"{i}:1380000000{i}") for i in range(1, 50)}
    assert len(codes) == 49


def test_ua_from_pool():
    ua = pick_ua("7:13900000007")
    assert ua in UA_POOL
    assert "Android" in ua


def test_ua_stable_per_account():
    assert pick_ua("7:13900000007") == pick_ua("7:13900000007")


def test_proxy_pool_empty():
    assert pick_proxy("x", None) is None
    assert pick_proxy("x", []) is None
    assert pick_proxy("x", ["", "  "]) is None


def test_proxy_index_hint_spreads_without_collision():
    pool = ["p0", "p1", "p2", "p3"]
    got = [pick_proxy("s", pool, index_hint=i) for i in range(4)]
    assert len(set(got)) == 4


def test_proxy_wraps_when_pool_smaller_than_accounts():
    pool = ["p0", "p1"]
    got = [pick_proxy("s", pool, index_hint=i) for i in range(6)]
    assert set(got) == {"p0", "p1"}
    assert got.count("p0") == 3


def test_build_prefers_saved_fields():
    """身份一旦落库就不再重算，避免"同一学号换设备"。"""
    ident = build(3, "13800000003", device_code="deadbeef" * 4, ua="MY-UA", proxy="http://p:1")
    assert ident.device_code == "deadbeef" * 4
    assert ident.ua == "MY-UA"
    assert ident.proxy == "http://p:1"


def test_build_derives_when_missing():
    ident = build(3, "13800000003", proxy_pool=["a", "b", "c"])
    assert len(ident.device_code) == 32
    assert ident.ua in UA_POOL
    assert ident.proxy in {"a", "b", "c"}


def test_identity_to_row():
    row = Identity("x" * 32, "UA", None).to_row()
    assert row == {"device_code": "x" * 32, "ua": "UA", "proxy": ""}
