"""普通签到 / 手势签到 / 签到码签到。

这三种在协议上是同一个请求，差别只在：
* 手势：老师画完手势后活动自动开放，学生端**什么都不用提交**
* 签到码：需要额外带上 ``signCode``

⚠️ 关于签到码预校验：多个第三方库文档里提到 ``pptSign/stu/checkSignCode``，
实测（2026-11）该路径返回 **tengine 500**，服务端并不存在这个接口。
所以默认不预校验，直接把 `signCode` 带在提交里 —— 服务端自己会判对错。
"""

from __future__ import annotations

from ..activity import Activity, SignKind
from ..endpoints import CHECK_SIGN_CODE, CHECK_SIGN_CODE_WORKS
from ..net import Session
from .base import SignOptions, SignResult, base_params, submit


def check_sign_code(session: Session, activity_id: str, code: str) -> tuple[bool, str]:
    """签到码预校验（默认关闭，接口实测不存在）。"""
    if not CHECK_SIGN_CODE_WORKS:
        return False, "预校验接口在服务端不存在（实测 tengine 500），直接提交"
    try:
        resp = session.get(
            CHECK_SIGN_CODE,
            params={"activeId": activity_id, "signCode": code},
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"预校验请求异常：{exc}"
    text = (resp.text or "").strip()
    ok = text.lower() in ("success", "true", "1") or "成功" in text
    return ok, text[:120]


def sign_general(
    session: Session,
    activity: Activity,
    opts: SignOptions,
    *,
    kind: SignKind = SignKind.PLAIN,
) -> SignResult:
    params = base_params(session, activity, opts)
    params.update({"latitude": "-1", "longitude": "-1"})
    if opts.sign_code:
        params["signCode"] = opts.sign_code

    ok, msg, url = submit(session, params)
    return SignResult(ok=ok, message=msg, kind=kind, raw=msg, request_url=url)


def sign_signcode(session: Session, activity: Activity, opts: SignOptions) -> SignResult:
    """签到码签到：先校验再提交。"""
    if opts.sign_code:
        check_sign_code(session, activity.active_id, opts.sign_code)
    return sign_general(session, activity, opts, kind=SignKind.SIGNCODE)
