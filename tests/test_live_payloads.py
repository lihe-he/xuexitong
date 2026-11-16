"""用真实服务端返回的报文做回归测试。

这些字符串全部来自 2026-11 对生产环境的实测（见 ``tools/probe_endpoints.py``），
不是构造的。改动协议层时先跑这个文件。
"""

from __future__ import annotations

import pytest

from cxsign.activity import is_logged_out_payload
from cxsign.net import Session
from cxsign.presign import analysis
from cxsign.signer.base import is_logged_out_reply, parse_reply

# ------------------------------------------------- analysis 的真实返回
REAL_ANALYSIS = (
    "$.ajax({type:'get',url:'/pptSign/analysis2?DB_STRATEGY=RANDOM&code"
    "='+'a739c0d230f97395c474edc5ee55762e',success:function(res){});"
)


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeSession:
    def __init__(self, text: str) -> None:
        self._text = text

    def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _FakeResp(self._text)


def test_analysis_extracts_real_code():
    code = analysis(_FakeSession(REAL_ANALYSIS), "1")
    assert code == "a739c0d230f97395c474edc5ee55762e"


def test_analysis_tolerates_html_wrapper():
    """真实响应被包在 JSON 字符串里时首尾有引号。"""
    code = analysis(_FakeSession('"' + REAL_ANALYSIS + '"'), "1")
    assert code == "a739c0d230f97395c474edc5ee55762e"


def test_analysis_returns_empty_on_unknown_page():
    assert analysis(_FakeSession("<html>维护中</html>"), "1") == ""


# ------------------------------------------------- 未登录跳转 Location
@pytest.mark.parametrize(
    ("location", "logged_out"),
    [
        # activelist / webim 实测
        ("https://passport2.chaoxing.com/mlogin?newversion=true&refer=https%3A%2F%2Fi.chaoxing.com",
         True),
        ("http://passport2.chaoxing.com/wlogin?refer=https%3A%2F%2Fim.chaoxing.com", True),
        # preSign 实测 —— 这条最容易被漏掉
        ("/widget/mobileError?errormsg=%E8%AF%B7%E7%99%BB%E5%BD%95%E5%90%8E%E5%86%8D%E8%BF%9B%E8%A1%8C%E7%AD%BE%E5%88%B0",
         True),
        # 正常业务跳转
        ("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid=1", False),
        ("", False),
    ],
)
def test_logged_out_location(location, logged_out):
    assert Session._logged_out_location(location) is logged_out


# ------------------------------------------------- 未登录纯文本回执
@pytest.mark.parametrize(
    "text",
    [
        "请先登录再进行签到",      # pptSign/stuSignajax
        "用户未登录",              # sign/preStuSign
        "未登陆或其他",            # sign/stuSignajax
        "请先登录",
    ],
)
def test_is_logged_out_reply_true(text):
    assert is_logged_out_reply(text)


@pytest.mark.parametrize("text", ["success", "success2", "fail", "距离签到位置 512 米", ""])
def test_is_logged_out_reply_false(text):
    assert not is_logged_out_reply(text)


def test_logout_reply_never_parsed_as_success():
    ok, msg = parse_reply("请先登录再进行签到")
    assert not ok
    assert msg


# ------------------------------------------------- 未登录 JSON 载荷
@pytest.mark.parametrize(
    "payload",
    [
        {"result": 0, "msg": None, "data": None, "errorMsg": "未登录或其他"},   # getPPTActiveInfo
        {"result": 0, "data": None, "errorMsg": "未登录"},
        {"result": 0, "errorMsg": "请登录"},
    ],
)
def test_is_logged_out_payload_true(payload):
    assert is_logged_out_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"result": 1, "data": {"activeList": []}},
        {"result": 1, "data": None},                      # 请求过频，不是未登录
        {"result": 0, "errorMsg": "系统繁忙"},            # 其它错误
        None,
        "not-a-dict",
    ],
)
def test_is_logged_out_payload_false(payload):
    assert not is_logged_out_payload(payload)


# ------------------------------------------------- checkSignCode 关闭
def test_check_sign_code_disabled_by_default():
    from cxsign.endpoints import CHECK_SIGN_CODE_WORKS
    from cxsign.signer.general import check_sign_code

    assert CHECK_SIGN_CODE_WORKS is False
    ok, msg = check_sign_code(None, "1", "1234")  # type: ignore[arg-type]
    assert ok is False
    assert "不存在" in msg
