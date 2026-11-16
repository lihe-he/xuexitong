"""二维码 enc 缓存池测试。"""

from __future__ import annotations

import time

import pytest

from cxsign.config import Settings
from cxsign.runtime import build


@pytest.fixture()
def rt(tmp_path):
    settings = Settings.load(tmp_path / "c.toml")
    settings.data_dir = tmp_path
    settings.database = tmp_path / "db.sqlite"
    runtime = build(settings)
    yield runtime
    runtime.close()


def test_enc_roundtrip(rt):
    rt.store.save_enc("active1", "1D0A628CK317")
    assert rt.store.get_enc("active1") == "1D0A628CK317"


def test_enc_missing(rt):
    assert rt.store.get_enc("nope") == ""


def test_enc_ttl_expired(rt):
    rt.store.save_enc("active1", "OLD")
    # 伪造一条 1 小时前的记录
    import json

    rt.store.kv_set(
        "enc:active1",
        json.dumps({"enc": "OLD", "ts": int(time.time()) - 3600, "source": "t"}),
    )
    assert rt.store.get_enc("active1", max_age=60) == ""
    assert rt.store.get_enc("active1", max_age=0) == "OLD"      # 0 = 不限


def test_enc_ttl_within_window(rt):
    rt.store.save_enc("active1", "FRESH")
    assert rt.store.get_enc("active1", max_age=120) == "FRESH"


def test_enc_info_reports_age(rt):
    rt.store.save_enc("active1", "X", source="shot.png")
    info = rt.store.enc_info("active1")
    assert info is not None
    assert info["enc"] == "X"
    assert info["source"] == "shot.png"
    assert info["age"] >= 0


def test_enc_info_missing(rt):
    assert rt.store.enc_info("nope") is None


def test_enc_overwrite(rt):
    rt.store.save_enc("active1", "A")
    rt.store.save_enc("active1", "B")
    assert rt.store.get_enc("active1") == "B"


def test_bad_json_ignored(rt):
    rt.store.kv_set("enc:broken", "not json")
    assert rt.store.get_enc("broken") == ""


def test_enc_isolation_between_activities(rt):
    rt.store.save_enc("a1", "E1")
    rt.store.save_enc("a2", "E2")
    assert rt.store.get_enc("a1") == "E1"
    assert rt.store.get_enc("a2") == "E2"


def test_sign_uses_cached_enc_when_missing(rt, monkeypatch):
    """engine.sign 在没显式给 enc 时应回落到缓存。"""
    from cxsign.activity import Activity, SignKind
    from cxsign.course import Course
    from cxsign.signer import SignOptions

    out = rt.engine.import_cookies("138", "_uid=1; fid=2")
    account = rt.store.get_account(out["account_id"])
    rt.store.save_enc("act-9", "CACHED-ENC")

    captured: dict = {}

    import cxsign.engine as engine_mod

    def fake_do_sign(sess, target, opts, **kw):  # noqa: ANN001, ANN003
        captured["enc"] = opts.enc
        return engine_mod.SignResult(ok=True, message="ok", kind=target.kind)

    monkeypatch.setattr(engine_mod, "do_sign", fake_do_sign)
    monkeypatch.setattr(engine_mod.auth, "validate", lambda _s: True)

    act = Activity("act-9", "扫码", Course("1", "2"), SignKind.QRCODE)
    rt.engine.sign(account.id, act, SignOptions())
    assert captured["enc"] == "CACHED-ENC"
