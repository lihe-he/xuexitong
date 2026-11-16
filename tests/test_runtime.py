"""Store / Engine 的集成测试：加密落库、退避、Cookie 托管、审计。"""

from __future__ import annotations

import pytest

from cxsign.config import Settings
from cxsign.net import CxError
from cxsign.runtime import build
from cxsign.security import SecretBox


@pytest.fixture()
def rt(tmp_path):
    settings = Settings.load(tmp_path / "config.toml")
    settings.data_dir = tmp_path
    settings.database = tmp_path / "cxsign.db"
    runtime = build(settings)
    yield runtime
    runtime.close()


# ------------------------------------------------------------- 加密落库
def test_password_encrypted_at_rest(rt):
    rt.store.upsert_account("13800000002", password="MyP@ssw0rd")
    raw = rt.store._conn.execute(
        "SELECT password FROM accounts WHERE username='13800000002'"
    ).fetchone()[0]
    assert SecretBox.is_encrypted(raw)
    assert "MyP@ssw0rd" not in raw
    assert rt.store.get_account_by_name("13800000002").password == "MyP@ssw0rd"


def test_password_update_reencrypts(rt):
    rt.store.upsert_account("138", password="old")
    rt.store.upsert_account("138", password="new")
    assert rt.store.get_account_by_name("138").password == "new"


def test_legacy_plaintext_upgraded_on_open(tmp_path):
    """老库里的明文密码，下次启动会自动加密。"""
    settings = Settings.load(tmp_path / "c.toml")
    settings.data_dir = tmp_path
    settings.database = tmp_path / "legacy.db"

    from cxsign.store import Store

    plain = Store(settings.database)          # 不带 secret
    plain.upsert_account("139", password="plaintext-pw")
    plain.close()

    secret = SecretBox.load(tmp_path)
    upgraded = Store(settings.database, secret=secret)
    raw = upgraded._conn.execute("SELECT password FROM accounts WHERE username='139'").fetchone()[0]
    assert SecretBox.is_encrypted(raw)
    assert upgraded.get_account_by_name("139").password == "plaintext-pw"
    upgraded.close()


# ----------------------------------------------------------------- 退避
def test_backoff_is_exponential(rt):
    assert rt.engine.note_throttled(1) == rt.settings.backoff_base
    assert rt.engine.note_throttled(1) == rt.settings.backoff_base * 2
    assert rt.engine.note_throttled(1) == rt.settings.backoff_base * 4


def test_backoff_capped(rt):
    for _ in range(20):
        rt.engine.note_throttled(1)
    assert rt.engine.cooling_down(1) <= rt.settings.backoff_max


def test_backoff_cleared_on_success(rt):
    rt.engine.note_throttled(1)
    assert rt.engine.cooling_down(1) > 0
    rt.engine.note_ok(1)
    assert rt.engine.cooling_down(1) == 0


def test_scan_respects_backoff(rt):
    """退避中的账号直接返回空，不去打接口。"""
    rt.store.upsert_account("13700000000", password="x")
    account = rt.store.get_account_by_name("13700000000")
    rt.engine.note_throttled(account.id)
    assert rt.engine.scan(account.id) == []


# ------------------------------------------------------------ Cookie 托管
def test_import_cookies(rt):
    out = rt.engine.import_cookies(
        "13800000009", "_uid=111; fid=2222; _d=xyz", operator="TA-01", note="口头授权"
    )
    assert out["mode"] == "cookie"
    assert out["delegation_id"] > 0

    account = rt.store.get_account(out["account_id"])
    assert account.cookies["_uid"] == "111"
    assert account.password == ""          # 托管模式不留密码
    assert account.device_code             # 身份已固化
    assert account.owner == "TA-01"


def test_import_cookies_requires_uid(rt):
    with pytest.raises(CxError):
        rt.engine.import_cookies("13800000010", "fid=2222")


def test_import_creates_delegation_record(rt):
    out = rt.engine.import_cookies("138", "_uid=1; fid=2", operator="TA-02")
    record = rt.store.active_delegation(out["account_id"])
    assert record is not None
    assert record["operator"] == "TA-02"
    assert record["revoked"] == 0


def test_revoke_delegation(rt):
    out = rt.engine.import_cookies("138", "_uid=1; fid=2", operator="TA-03")
    rt.store.revoke_delegation(out["delegation_id"])
    assert rt.store.active_delegation(out["account_id"]) is None


# ----------------------------------------------------------------- 审计
def test_log_carries_operator(rt):
    out = rt.engine.import_cookies("138", "_uid=1; fid=2", operator="TA-04")
    rt.store.add_log(
        out["account_id"], "555", kind="plain", ok=True, message="ok",
        delegation_id=out["delegation_id"],
    )
    rows = rt.store.logs_with_operator(10)
    assert rows[0]["operator"] == "TA-04"
    assert rows[0]["delegation"] == out["delegation_id"]


def test_cookie_account_cannot_auto_relogin(rt):
    """Cookie 托管模式没有密码，登录态失效时应该抛 AuthExpired 而不是静默失败。"""
    from cxsign.net import AuthExpired

    out = rt.engine.import_cookies("138", "_uid=1; fid=2")
    account = rt.store.get_account(out["account_id"])

    class _AlwaysInvalid:
        def validate(self, _sess):
            return False

    import cxsign.engine as engine_mod

    original = engine_mod.auth.validate
    engine_mod.auth.validate = lambda _sess: False
    try:
        with pytest.raises(AuthExpired):
            rt.engine.ensure_session(account)
    finally:
        engine_mod.auth.validate = original


# ----------------------------------------------------------------- 删除
def test_delete_account_removes_related_rows(rt):
    out = rt.engine.import_cookies("138", "_uid=1; fid=2", operator="TA")
    aid = out["account_id"]
    rt.store.replace_courses(aid, [{"course_id": "1", "class_id": "2", "name": "x"}])
    rt.store.add_log(aid, "999", kind="plain", ok=True, message="ok")

    assert rt.store.delete_account(aid) is True
    assert rt.store.get_account(aid) is None
    assert rt.store.list_courses(aid) == []
    assert rt.store.active_delegation(aid) is None
    # 日志保留（审计需要）
    assert any(row["account_id"] == aid for row in rt.store.recent_logs(10))


def test_delete_missing_account(rt):
    assert rt.store.delete_account(9999) is False
