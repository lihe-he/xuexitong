"""签到提交层：把 Activity 落到 `pptSign/stuSignajax`。

统一约定：
* 所有类型最终都打 ``STU_SIGN_AJAX``（群聊活动除外，见 chat 模块）
* 返回体是**纯文本**，不是 JSON，成功字面量是 ``success`` / ``success2``
* 位置签到失败时返回「距离签到位置 X 米」，这是唯一能用来调坐标的反馈
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..activity import Activity, SignKind
from ..config import SUCCESS_TOKENS
from ..net import AuthExpired, Session

#: 未登录时 stuSignajax 返回的纯文本（实测 2026-11）
_LOGGED_OUT_REPLIES = ("请先登录", "未登录", "未登陆", "用户未登录", "请登录")


def is_logged_out_reply(text: str) -> bool:
    """签到接口未登录时**不跳 302**，而是 200 + 一句中文。

    实测：
        pptSign/stuSignajax  → "请先登录再进行签到"
        sign/stuSignajax     → "用户未登录" / "未登陆或其他"
    """
    t = (text or "").strip()
    return any(h in t for h in _LOGGED_OUT_REPLIES)


@dataclass(slots=True)
class SignOptions:
    """签到需要的全部外部输入。按类型取用，多余的忽略。"""

    name: str = ""                  # 真实姓名
    sign_code: str = ""             # 签到码
    enc: str = ""                   # 二维码 enc
    lat: str = "-1"
    lon: str = "-1"
    address: str = ""               # 位置签到的文字地址
    altitude: str = "100"
    object_id: str = ""             # 拍照签到的云盘 objectId
    device_code: str = ""           # 设备标识，留空即可
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SignResult:
    ok: bool
    message: str
    kind: SignKind
    raw: str = ""
    request_url: str = ""

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        flag = "✅" if self.ok else "❌"
        return f"{flag} {self.kind.value}: {self.message}"


def parse_reply(text: str) -> tuple[bool, str]:
    """把 stuSignajax 的纯文本回执翻译成 (是否成功, 人话)。"""
    t = (text or "").strip()
    low = t.lower()
    if low in SUCCESS_TOKENS:
        return True, "签到成功"
    if not t:
        return False, "接口返回空，可能被限流"
    mapping = {
        "fail": "签到失败",
        "fail-need-qrcode": "需要二维码",
        "validate": "需要滑块验证码验证",
        "签到失败，请重新扫描": "二维码已失效（enc 有时效）",
        "您已经签到过了": "已签到过",
    }
    for key, human in mapping.items():
        if key in t:
            return False, human
    if "米" in t and "距离" in t:
        return False, t
    return False, t[:200]


def submit(session: Session, params: dict[str, Any], *, method: str = "GET") -> tuple[bool, str, str]:
    """统一的提交入口。返回 (ok, message, url)。

    * 未登录抛 :class:`AuthExpired`，让 Engine 走重登重试，而不是当普通失败
    * **不重试**：签到是抢时间的动作，5xx 通常是参数问题而不是网络抖动，
      重试 3 次会白白拖掉 10 秒，把有效的 enc 拖过期
    """
    from .. import endpoints

    if method.upper() == "POST":
        resp = session.post(endpoints.STU_SIGN_AJAX, data=params, retries=1)
    else:
        resp = session.get(endpoints.STU_SIGN_AJAX, params=params, retries=1)
    text = resp.text
    if is_logged_out_reply(text):
        raise AuthExpired(f"签到接口返回未登录：{text.strip()[:60]}")
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}: {text[:80]}", str(resp.request.url)
    ok, msg = parse_reply(text)
    return ok, msg, str(resp.request.url)


def base_params(session: Session, activity: Activity, opts: SignOptions) -> dict[str, Any]:
    """所有签到类型共用的参数。

    ``deviceCode`` 是身份隔离的关键：同一个设备码签多个人的到，服务端一眼就能
    把账号串起来。所以这个值必须来自账号自己固定的那份身份（见 ``identity.py``）。
    """
    params: dict[str, Any] = {
        "activeId": activity.active_id,
        "uid": session.uid,
        "fid": session.fid,
        "courseId": activity.course.course_id,
        "classId": activity.course.class_id,
        "clientip": "",
        "appType": "15",
        "name": opts.name,
        "useragent": "",
    }
    if opts.device_code:
        params["deviceCode"] = opts.device_code
    return params
