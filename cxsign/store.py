"""SQLite 持久化。

四张表：

* ``accounts``  账号 + Cookie（Cookie 序列化成 JSON 存一列，整份保存）
* ``courses``   账号下的课程缓存
* ``sign_logs`` 每次签到尝试的结果，用于去重与审计
* ``kv``        杂项配置（比如上次同步时间）
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL DEFAULT '',
    real_name   TEXT NOT NULL DEFAULT '',
    cookies     TEXT NOT NULL DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 1,
    device_code TEXT NOT NULL DEFAULT '',
    ua          TEXT NOT NULL DEFAULT '',
    proxy       TEXT NOT NULL DEFAULT '',
    owner       TEXT NOT NULL DEFAULT '',
    remark      TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    course_id   TEXT NOT NULL,
    class_id    TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    UNIQUE(account_id, course_id, class_id)
);

CREATE TABLE IF NOT EXISTS sign_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    active_id   TEXT NOT NULL,
    course_id   TEXT NOT NULL DEFAULT '',
    class_id    TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT '',
    ok          INTEGER NOT NULL DEFAULT 0,
    message     TEXT NOT NULL DEFAULT '',
    delegation_id INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sign_logs_key ON sign_logs(account_id, active_id);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);

-- 代签审计：谁在什么时候把哪个账号托管给了谁
CREATE TABLE IF NOT EXISTS delegations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    operator    TEXT NOT NULL DEFAULT '',   -- 代为操作的人/标识
    grant_note  TEXT NOT NULL DEFAULT '',   -- 授权凭据摘要（哈希，不存原文）
    revoked     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    revoked_at  INTEGER NOT NULL DEFAULT 0
);
"""

#: 老库升级：逐列补齐（SQLite 没有 ADD COLUMN IF NOT EXISTS）
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "accounts": [
        ("device_code", "TEXT NOT NULL DEFAULT ''"),
        ("ua", "TEXT NOT NULL DEFAULT ''"),
        ("proxy", "TEXT NOT NULL DEFAULT ''"),
        ("owner", "TEXT NOT NULL DEFAULT ''"),
        ("remark", "TEXT NOT NULL DEFAULT ''"),
    ],
    "sign_logs": [
        ("delegation_id", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


@dataclass(slots=True)
class AccountRow:
    id: int
    username: str
    password: str
    real_name: str
    cookies: dict[str, str]
    enabled: bool
    updated_at: int
    device_code: str = ""
    ua: str = ""
    proxy: str = ""
    owner: str = ""
    remark: str = ""


class Store:
    def __init__(self, path: str | Path, secret: Any = None) -> None:
        self.path = str(path)
        self.secret = secret
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()
        if secret is not None:
            self._upgrade_passwords()

    def _migrate(self) -> None:
        """给老库补列，幂等。"""
        for table, columns in _MIGRATIONS.items():
            existing = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, ddl in columns:
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    # ------------------------------------------------------------ 密码加密
    def _enc_password(self, plaintext: str | None) -> str | None:
        if plaintext is None:
            return None
        if not plaintext:
            return ""
        if self.secret is None:
            return plaintext
        return self.secret.encrypt(plaintext)

    def _dec_password(self, stored: str) -> str:
        if not stored:
            return ""
        if self.secret is None:
            return stored
        try:
            return self.secret.decrypt(stored)
        except Exception:  # noqa: BLE001 —— 密钥换了也不该让整个库打不开
            return ""

    def _upgrade_passwords(self) -> None:
        """把历史明文密码就地加密。启动时跑一次，幂等。"""
        from .security import SecretBox

        with self._lock:
            rows = self._conn.execute("SELECT id, password FROM accounts").fetchall()
            upgraded = 0
            for row in rows:
                pw = row["password"]
                if pw and not SecretBox.is_encrypted(pw):
                    self._conn.execute(
                        "UPDATE accounts SET password=? WHERE id=?",
                        (self._enc_password(pw), row["id"]),
                    )
                    upgraded += 1
            if upgraded:
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ accounts
    def upsert_account(
        self,
        username: str,
        *,
        password: str | None = None,
        real_name: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> int:
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute("SELECT id FROM accounts WHERE username=?", (username,))
            row = cur.fetchone()
            if row:
                fields: list[str] = []
                values: list[Any] = []
                if password is not None:
                    fields.append("password=?")
                    values.append(self._enc_password(password))
                if real_name is not None:
                    fields.append("real_name=?")
                    values.append(real_name)
                if cookies is not None:
                    fields.append("cookies=?")
                    values.append(json.dumps(cookies, ensure_ascii=False))
                fields.append("updated_at=?")
                values.append(now)
                values.append(row["id"])
                self._conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id=?", values)
                self._conn.commit()
                return int(row["id"])

            cur = self._conn.execute(
                "INSERT INTO accounts(username, password, real_name, cookies, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (
                    username,
                    self._enc_password(password) or "",
                    real_name or "",
                    json.dumps(cookies or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def get_account(self, account_id: int) -> AccountRow | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return self._to_account(row) if row else None

    def get_account_by_name(self, username: str) -> AccountRow | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        return self._to_account(row) if row else None

    def list_accounts(self, only_enabled: bool = False) -> list[AccountRow]:
        sql = "SELECT * FROM accounts"
        if only_enabled:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [self._to_account(r) for r in rows]

    def set_enabled(self, account_id: int, enabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET enabled=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, int(time.time()), account_id),
            )
            self._conn.commit()

    def delete_account(self, account_id: int) -> bool:
        """物理删除账号及其课程/授权记录。签到日志保留（审计需要）。"""
        with self._lock:
            row = self._conn.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not row:
                return False
            self._conn.execute("DELETE FROM courses WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM delegations WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            self._conn.commit()
        return True

    def _to_account(self, row: sqlite3.Row) -> AccountRow:
        try:
            cookies = json.loads(row["cookies"])
        except Exception:  # noqa: BLE001
            cookies = {}
        keys = row.keys()

        def get(name: str, default: str = "") -> str:
            return row[name] if name in keys else default

        return AccountRow(
            id=int(row["id"]),
            username=row["username"],
            password=self._dec_password(row["password"]),
            real_name=row["real_name"],
            cookies=cookies,
            enabled=bool(row["enabled"]),
            updated_at=int(row["updated_at"]),
            device_code=get("device_code"),
            ua=get("ua"),
            proxy=get("proxy"),
            owner=get("owner"),
            remark=get("remark"),
        )

    # ------------------------------------------------------------ identity
    def save_identity(self, account_id: int, identity: Any) -> None:
        """把设备人格固化进库，保证同一账号身份永不漂移。"""
        row = identity.to_row() if hasattr(identity, "to_row") else dict(identity)
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET device_code=?, ua=?, proxy=?, updated_at=? WHERE id=?",
                (
                    row.get("device_code", ""),
                    row.get("ua", ""),
                    row.get("proxy", "") or "",
                    int(time.time()),
                    account_id,
                ),
            )
            self._conn.commit()

    def set_owner(self, account_id: int, owner: str, remark: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET owner=?, remark=?, updated_at=? WHERE id=?",
                (owner, remark, int(time.time()), account_id),
            )
            self._conn.commit()

    # --------------------------------------------------------- delegations
    def add_delegation(self, account_id: int, operator: str, grant_note: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO delegations(account_id, operator, grant_note, created_at) VALUES(?,?,?,?)",
                (account_id, operator, grant_note, int(time.time())),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def revoke_delegation(self, delegation_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE delegations SET revoked=1, revoked_at=? WHERE id=?",
                (int(time.time()), delegation_id),
            )
            self._conn.commit()

    def active_delegation(self, account_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM delegations WHERE account_id=? AND revoked=0 ORDER BY id DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------- courses
    def replace_courses(self, account_id: int, courses: list[dict[str, str]]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM courses WHERE account_id=?", (account_id,))
            self._conn.executemany(
                "INSERT OR REPLACE INTO courses(account_id, course_id, class_id, name) VALUES(?,?,?,?)",
                [(account_id, c["course_id"], c["class_id"], c.get("name", "")) for c in courses],
            )
            self._conn.commit()

    def list_courses(self, account_id: int) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT course_id, class_id, name FROM courses WHERE account_id=? ORDER BY id",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ sign_logs
    def add_log(
        self,
        account_id: int,
        active_id: str,
        *,
        course_id: str = "",
        class_id: str = "",
        kind: str = "",
        ok: bool = False,
        message: str = "",
        delegation_id: int = 0,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sign_logs(account_id, active_id, course_id, class_id, kind, ok, message,"
                " delegation_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    active_id,
                    course_id,
                    class_id,
                    kind,
                    1 if ok else 0,
                    message,
                    delegation_id,
                    int(time.time()),
                ),
            )
            self._conn.commit()

    def already_signed(self, account_id: int, active_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sign_logs WHERE account_id=? AND active_id=? AND ok=1 LIMIT 1",
                (account_id, active_id),
            ).fetchone()
        return row is not None

    def recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sign_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def logs_with_operator(self, limit: int = 100) -> list[dict[str, Any]]:
        """带授权来源的日志，回答"这次是谁授权签的"。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT l.*, d.operator AS operator, d.id AS delegation"
                " FROM sign_logs l LEFT JOIN delegations d ON d.id = l.delegation_id"
                " ORDER BY l.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?,?)", (key, value))
            self._conn.commit()

    def kv_del(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE k=?", (key,))
            self._conn.commit()

    def kv_keys(self, prefix: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT k FROM kv WHERE k LIKE ?", (prefix.replace("%", "") + "%",)
            ).fetchall()
        return [r["k"] for r in rows]

    # ------------------------------------------------- 二维码活动目标缓存
    def save_qr_target(
        self, account_id: int, active_id: str, course_id: str, class_id: str
    ) -> None:
        """记下"这个账号有个二维码签到等着 enc"。

        监听每 20 秒扫一遍，扫到就写进来；抢签器直接读，省掉一次 10 秒的全量扫描。
        """
        payload = json.dumps(
            {
                "active_id": active_id,
                "course_id": course_id,
                "class_id": class_id,
                "ts": int(time.time()),
            },
            ensure_ascii=False,
        )
        self.kv_set(f"qrtarget:{account_id}:{active_id}", payload)

    def get_qr_targets(self, account_id: int, max_age: int = 300) -> list[dict[str, Any]]:
        now = int(time.time())
        out: list[dict[str, Any]] = []
        for key in self.kv_keys(f"qrtarget:{account_id}:"):
            try:
                data = json.loads(self.kv_get(key))
            except json.JSONDecodeError:
                continue
            if max_age > 0 and now - int(data.get("ts", 0)) > max_age:
                self.kv_del(key)
                continue
            out.append(data)
        return out

    # ------------------------------------------------------- 二维码 enc 池
    def save_enc(self, active_id: str, enc: str, source: str = "") -> None:
        """缓存二维码 enc。

        一个 enc 不是绑学生的 —— 老师屏幕上那一张，谁扫都可以用。
        所以同一个班多个账号只需要捕获一次，其余复用。
        """
        payload = json.dumps(
            {"enc": enc, "ts": int(time.time()), "source": source}, ensure_ascii=False
        )
        self.kv_set(f"enc:{active_id}", payload)

    def get_enc(self, active_id: str, max_age: int = 0) -> str:
        raw = self.kv_get(f"enc:{active_id}")
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        if max_age > 0 and int(time.time()) - int(data.get("ts", 0)) > max_age:
            return ""
        return str(data.get("enc") or "")

    def enc_info(self, active_id: str) -> dict[str, Any] | None:
        raw = self.kv_get(f"enc:{active_id}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        data["age"] = int(time.time()) - int(data.get("ts", 0))
        return data
