"""登录、登录态校验、取真实姓名。"""

from __future__ import annotations

import re

from . import crypto, endpoints
from .net import ApiError, AuthExpired, Session


class LoginError(ApiError):
    """账号密码错误 / 需要验证码 / 被风控。"""


_NAME_RE = re.compile(r'id="messageName"\s+value="([^"]*)"')
_NAME_RE2 = re.compile(r"messageName[^>]*value=\"([^\"]*)\"")
#: 2026-11 的 accountManage 结构：姓名在「姓名」这一行的 p 里
_NAME_RE3 = re.compile(r'<p class="fr colorBlue">\s*([^<]+?)\s*</p>\s*姓名')
#: 兜底：实名认证那一行 <i ...></i>张三（已认证）</p>
_NAME_RE4 = re.compile(r'</i>\s*([^<（(]{2,20})\s*[（(]已认证')
_SCHOOL_RE = re.compile(r'</i>\s*([^<]{2,40}?)\s*</p>单位设置')


def login(session: Session, username: str, password: str) -> dict[str, str]:
    """手机号 + 密码登录，成功后 Cookie 会写回 session。

    返回 Cookie 字典，方便持久化。

    学习通会在某些 IP / 频率下要求滑块验证（``fanyalogin`` 返回
    ``status=False`` 且 ``msg2`` 提示验证），此时抛 :class:`LoginError`。
    """
    payload = {
        "fid": "-1",
        "uname": username,
        "password": crypto.aes_encrypt(password),
        "refer": "https%3A%2F%2Fi.chaoxing.com",
        "t": "true",
        "forbidotherlogin": "0",
        "validate": "",
        "doubleFactorLogin": "0",
        "independentId": "0",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://passport2.chaoxing.com",
        "Referer": "https://passport2.chaoxing.com/mlogin?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com",
    }
    resp = session.post(endpoints.LOGIN, data=payload, headers=headers)
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise LoginError(f"登录接口返回非 JSON：{resp.text[:200]}") from exc

    if not data.get("status"):
        msg = data.get("msg2") or data.get("msg") or "未知原因"
        # 兼容旧版 DES 加密
        payload["password"] = crypto.des_encrypt(password)
        resp2 = session.post(endpoints.LOGIN, data=payload, headers=headers)
        try:
            data2 = resp2.json()
        except Exception:  # noqa: BLE001
            data2 = {}
        if not data2.get("status"):
            raise LoginError(f"登录失败：{msg}")
        data = data2

    cookies = session.cookies
    if "_uid" not in cookies and "UID" not in cookies:
        raise LoginError("登录接口返回成功但未拿到 _uid Cookie，可能被风控拦截")
    return cookies


def whoami(session: Session) -> str:
    """取真实姓名（用于签到参数 name，很多老师靠这个核对）。

    遍历多种页面结构，命中即返回。2026-11 实测第 3 条正则有效。
    """
    try:
        resp = session.get(endpoints.ACCOUNT_MANAGE)
    except AuthExpired:
        raise
    text = resp.text
    for pattern in (_NAME_RE, _NAME_RE2, _NAME_RE3, _NAME_RE4):
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            if name and name not in ("姓名", "未设置", "设置"):
                return name
    return ""


def school_of(session: Session) -> str:
    """取机构名（顺带给 UI 展示）。取不到返回空串。"""
    try:
        text = session.get(endpoints.ACCOUNT_MANAGE).text
    except AuthExpired:
        raise
    m = _SCHOOL_RE.search(text)
    return m.group(1).strip() if m else ""


def validate(session: Session) -> bool:
    """校验 Cookie 是否仍有效。比请求 /base 更准，且不会误判。"""
    if not session.cookies.get("_uid") and not session.cookies.get("UID"):
        return False
    try:
        resp = session.post(
            endpoints.COURSE_LIST,
            data={"courseType": "1", "courseFolderId": "0", "courseFolderSize": "0"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    except (AuthExpired, ApiError):
        return False

    if resp.status_code >= 400:
        return False
    # 有效会话一定返回课程列表 HTML（含 course_ 或"暂无课程"）
    body = resp.text
    return ("course_" in body) or ("暂无" in body) or len(body) > 2000


def ensure_login(session: Session, username: str = "", password: str = "") -> bool:
    """确保登录态可用；有账号密码则自动重登。返回是否可用。"""
    if validate(session):
        return True
    if not (username and password):
        return False
    login(session, username, password)
    return validate(session)
