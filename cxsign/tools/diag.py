"""诊断：手里的 Cookie 在哪些域仍然有效、缺哪个关键字段。

排查"为什么明明登录了却 302"时第一个该跑的命令。
"""

from __future__ import annotations

import argparse
import sys

import httpx

from ..config import DEFAULT_UA, Settings
from ..course import parse_cookies
from ..runtime import build
from ..security import SecretBox

#: 少一个就会全线 302 的字段
CRITICAL = ("_uid", "fid", "vc3")

PROBES = [
    ("activelist", "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist",
     {"fid": "0", "courseId": "1", "classId": "1", "_": "1"}),
    ("getPPTActiveInfo", "https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo",
     {"activeId": "1"}),
    ("courselistdata", "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata", None),
    ("i.chaoxing.com/base", "https://i.chaoxing.com/base", None),
    ("pan token", "https://pan-yz.chaoxing.com/api/token/uservalid", None),
    ("webim/me", "https://im.chaoxing.com/webim/me", None),
]


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    settings = Settings.load(args.config)
    rt = build(settings)
    try:
        accounts = rt.store.list_accounts()
        if not accounts:
            print("没有账号，先 login 或 catcher")
            return 1

        for account in accounts:
            print(f"\n=== {account.username}（{account.real_name or '-'}）===")
            cookies = account.cookies
            print(f"  cookie {len(cookies)} 项：{', '.join(sorted(cookies))}")
            missing = [k for k in CRITICAL if k not in cookies]
            if missing:
                print(f"  ⚠️ 缺少关键字段：{', '.join(missing)}（会导致全线 302）")
            print(f"  密码：{'已加密存储' if SecretBox.is_encrypted(account.password) or account.password else '(空)'}")

            with httpx.Client(
                timeout=15,
                follow_redirects=False,
                headers={"User-Agent": settings.ua or DEFAULT_UA},
                cookies=cookies,
            ) as client:
                for name, url, params in PROBES:
                    try:
                        if name == "courselistdata":
                            resp = client.post(
                                url,
                                data={"courseType": "1", "courseFolderId": "0", "courseFolderSize": "0"},
                                headers={"X-Requested-With": "XMLHttpRequest"},
                            )
                        else:
                            resp = client.get(url, params=params)
                    except httpx.HTTPError as exc:
                        print(f"  {name:<20} ERR {exc}")
                        continue
                    loc = (resp.headers.get("location") or "")[:48]
                    ok = resp.status_code == 200 and "未登录" not in resp.text[:200]
                    flag = "✅" if ok else "❌"
                    print(f"  {name:<20} {flag} {resp.status_code}  {loc or resp.text[:48].replace(chr(10), ' ')}")
        return 0
    finally:
        rt.close()


def parse_raw(raw: str) -> dict[str, str]:
    """给脚本复用：把粘贴的 cookie 串归一。"""
    return parse_cookies(raw)
