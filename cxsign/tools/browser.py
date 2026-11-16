"""从本机 Chromium 系 profile 导出学习通 Cookie。

## 什么时候用

拿不到密码、又不想手动抄 Cookie 时。比 ``document.cookie`` 更全 —— 它读的是
磁盘上的 SQLite，**包含 HttpOnly 的 vc3**。

## 已知限制（实测）

* Electron 应用（如 DSH 桌面端）会用 ``dwShareMode=0`` 独占打开 cookie 库，
  非管理员进程连读都读不了（``ERROR_SHARING_VIOLATION=32``）。这种情况请用
  ``python -m cxsign.tools catcher`` 手工粘贴。
* Chrome 127+ 的 cookie 可能用 App-Bound Encryption（``v20`` 前缀），
  用户态解不开，会明确报错。

## 解密原理

``Local State`` 里的 ``os_crypt.encrypted_key`` 是 DPAPI 包着的 AES-256 密钥，
解出来后再用 AES-GCM 解每条 ``v10``/``v11`` cookie。
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import sqlite3
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

WANTED_HOSTS = ("chaoxing.com", "xuexitong.com", "chaoxing.cn")
DEFAULT_PROFILE = Path(os.path.expandvars(r"%APPDATA%\@deepseek-ai\dsh-desktop"))


# ------------------------------------------------------------------ DPAPI
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def dpapi_decrypt(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in, blob_out = _blob(data), _BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError(f"CryptUnprotectData 失败：{ctypes.get_last_error()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def master_key(profile: Path) -> bytes:
    state = profile / "Local State"
    raw = base64.b64decode(json.loads(state.read_text(encoding="utf-8"))["os_crypt"]["encrypted_key"])
    if raw[:5] != b"DPAPI":
        raise RuntimeError(f"未知的 key 封装格式：{raw[:5]!r}")
    return dpapi_decrypt(raw[5:])


def decrypt_value(enc: bytes, key: bytes) -> str:
    if not enc:
        return ""
    prefix = enc[:3]
    if prefix in (b"v10", b"v11"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(key).decrypt(enc[3:15], enc[15:], None).decode("utf-8", "replace")
    if prefix == b"v20":
        raise RuntimeError("cookie 使用 App-Bound Encryption（v20），用户态无法解密")
    return dpapi_decrypt(enc).decode("utf-8", "replace")


# ------------------------------------------------------------------ 读取
def probe_readable(cookie_db: Path) -> bool:
    """用共享模式试着打开，判断是否被独占锁定。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    h = k32.CreateFileW(str(cookie_db), 0x80000000, 0x7, None, 3, 0x80, None)
    if h == ctypes.c_void_p(-1).value or h is None:
        return False
    k32.CloseHandle(h)
    return True


def export(profile: Path) -> dict[str, dict[str, str]]:
    src = profile / "Network" / "Cookies"
    if not src.is_file():
        raise FileNotFoundError(f"找不到 Cookies 库：{src}")
    if not probe_readable(src):
        raise PermissionError(
            f"{src} 被应用独占锁定（ERROR_SHARING_VIOLATION），"
            "请改用 `python -m cxsign.tools catcher` 手工粘贴"
        )

    tmp = Path(tempfile.gettempdir()) / "_cxsign_ck.db"
    for suffix in ("", "-wal", "-shm"):
        target, source = Path(str(tmp) + suffix), Path(str(src) + suffix)
        if source.is_file():
            try:
                target.write_bytes(source.read_bytes())
            except OSError:
                continue
        elif target.is_file():
            target.unlink()

    key = master_key(profile)
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT host_key, name, value, encrypted_value FROM cookies").fetchall()
    con.close()

    out: dict[str, dict[str, str]] = {}
    for row in rows:
        host = row["host_key"]
        if not any(w in host for w in WANTED_HOSTS):
            continue
        value = row["value"]
        if not value:
            try:
                value = decrypt_value(row["encrypted_value"], key)
            except Exception:  # noqa: BLE001
                continue
        if value:
            out.setdefault(host, {})[row["name"]] = value
    return out


def scan_all() -> list[tuple[Path, dict[str, dict[str, str]]]]:
    roots = [Path(os.path.expandvars(r"%APPDATA%")), Path(os.path.expandvars(r"%LOCALAPPDATA%"))]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            try:
                found.extend(p for p in root.rglob("Cookies") if p.is_file() and p.parent.name == "Network")
            except OSError:
                continue

    results = []
    for db in sorted(set(found)):
        profile = db.parent.parent
        try:
            data = export(profile)
        except Exception:  # noqa: BLE001
            continue
        if data:
            results.append((db, data))
    return results


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    if args.scan:
        results = scan_all()
        if not results:
            print("没有找到含学习通 cookie 且可读的 profile")
            return 1
        for db, data in results:
            total = sum(len(v) for v in data.values())
            print(f"★ {total} 个  {db}")
            for host, cookies in data.items():
                print(f"    {host}: {', '.join(sorted(cookies))}")
        return 0

    profile = Path(args.profile) if args.profile else DEFAULT_PROFILE
    try:
        data = export(profile)
    except (FileNotFoundError, PermissionError, RuntimeError) as exc:
        print(f"失败：{exc}")
        return 2

    if not data:
        print("该 profile 里没有学习通 cookie")
        return 1

    merged: dict[str, str] = {}
    for cookies in data.values():
        merged.update(cookies)

    print(f"从 {profile} 导出 {len(merged)} 项：{', '.join(sorted(merged))}")
    if "vc3" not in merged:
        print("⚠️ 缺少 vc3，mobilelearn 会 302 到登录页 —— 换一个已登录学习通的浏览器 profile")

    if args.show:
        for name, value in sorted(merged.items()):
            shown = value if len(value) <= 14 else value[:6] + "…" + value[-4:]
            print(f"  {name} = {shown}")
    else:
        print("完整值：")
        print("  " + "; ".join(f"{k}={v}" for k, v in merged.items()))
    return 0
