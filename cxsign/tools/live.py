"""真实登录 + 只读链路验证。

只做：登录 → 校验 → 取姓名 → 同步课程 → 扫描进行中的签到 → 查详情。
**不提交任何签到**，提交需要另外显式触发。
"""

from __future__ import annotations

import argparse
import sys

from .. import auth
from ..activity import describe, get_active_info
from ..config import Settings
from ..runtime import build


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    rt = build(Settings.load(args.config))
    try:
        print(f"密钥来源: {rt.secret.source}")

        print("\n[1] 登录 fanyalogin ...")
        try:
            info = rt.engine.login_and_save(args.user, args.password)
        except Exception as exc:  # noqa: BLE001
            print(f"    登录失败: {exc}")
            return 2
        print(f"    account_id = {info['account_id']}")
        print(f"    真实姓名   = {info['real_name'] or '(未取到)'}")

        account = rt.store.get_account(info["account_id"])
        assert account is not None
        print(f"    cookie 项  = {len(account.cookies)}: {', '.join(sorted(account.cookies))}")
        print(f"    含 vc3     = {'vc3' in account.cookies}")
        print(f"    设备身份   = {account.device_code[:8]}… | 出口 {account.proxy or '直连'}")
        print(f"    密码落库   = {'已加密' if account.password else '(空)'}")

        session = rt.engine.session_of(account)

        print("\n[2] 登录态校验 ...")
        print(f"    validate = {auth.validate(session)}")
        print(f"    whoami   = {auth.whoami(session) or '(空)'}")
        print(f"    school   = {auth.school_of(session) or '(空)'}")

        print("\n[3] 同步课程 ...")
        try:
            courses = rt.engine.sync_courses(account.id)
        except Exception as exc:  # noqa: BLE001
            print(f"    失败: {exc}")
            courses = []
        for c in courses[:40]:
            print(f"    {c['course_id']:>12}  {c['class_id']:>10}  {c['name']}")
        print(f"    共 {len(courses)} 门")

        print("\n[4] 扫描进行中的签到 ...")
        try:
            activities = rt.engine.scan(account.id, use_backoff=False)
        except Exception as exc:  # noqa: BLE001
            print(f"    失败: {exc}")
            activities = []
        if not activities:
            print("    当前没有进行中的签到")
        for a in activities:
            hint = f"  需 {a.needs_input}" if a.needs_input else ""
            print(
                f"    {a.active_id}  {describe(a.kind):<6} {a.course}  {a.name}"
                f"  ({a.age_seconds:.0f}s 前){hint}"
            )

        if activities:
            print("\n[5] 活动详情 ...")
            for a in activities[:5]:
                try:
                    d = get_active_info(session, a.active_id)
                    keys = ("nameOne", "otherId", "ifphoto", "activeSort", "startTime", "endTime")
                    print(f"    {a.active_id}: " + ", ".join(f"{k}={d.get(k)!r}" for k in keys if k in d))
                except Exception as exc:  # noqa: BLE001
                    print(f"    {a.active_id}: {exc}")
        return 0
    finally:
        rt.close()
