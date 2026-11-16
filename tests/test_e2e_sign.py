"""端到端签到测试：真的发 HTTP 请求，只是服务端是本地的。

覆盖六种签到的**参数拼装**和**回执解析**，以及反作弊上报链是否真的被调用。
这是全项目唯一一组"从 Session 打到网络层"的测试。
"""

from __future__ import annotations

import pytest

from cxsign.activity import Activity, SignKind, get_active_info, list_activities
from cxsign.course import Course
from cxsign.net import AuthExpired, Session
from cxsign.signer import SignOptions, sign
from cxsign.signer.base import parse_reply

COURSE = Course(course_id="200000000", class_id="300000000", name="数据结构及算法")


@pytest.fixture()
def session(fake_cx):
    # 限速关掉，测试不该等
    return Session(min_interval=0, retries=1, cookies={"_uid": "400000000", "fid": "10001"})


def make_activity(kind: SignKind, active_id: str = "900001") -> Activity:
    return Activity(
        active_id=active_id,
        name="签到",
        course=COURSE,
        kind=kind,
        other_id=0,
        start_time=0,
    )


# ------------------------------------------------------------- 反作弊链
def test_presign_chain_runs(fake_cx, session):
    """preSign → analysis → analysis2 必须三步齐全，且 code 被正确带过去。"""
    sign(session, make_activity(SignKind.PLAIN), SignOptions(name="张三"))

    assert fake_cx.called("newsign/preSign"), "没有调 preSign"
    assert fake_cx.called("pptSign/analysis"), "没有调 analysis"
    assert fake_cx.called("pptSign/analysis2"), "没有调 analysis2"

    code = fake_cx.last_params("pptSign/analysis2")["code"]
    assert code == "a739c0d230f97395c474edc5ee55762e"


def test_presign_carries_active_and_course(fake_cx, session):
    sign(session, make_activity(SignKind.PLAIN), SignOptions(name="张三"))
    params = fake_cx.last_params("newsign/preSign")
    assert params["activePrimaryId"] == "900001"
    assert params["courseId"] == "200000000"
    assert params["classId"] == "300000000"
    assert params["uid"] == "400000000"


def test_skip_presign(fake_cx, session):
    sign(session, make_activity(SignKind.PLAIN), SignOptions(), skip_presign=True)
    assert not fake_cx.called("newsign/preSign")
    assert fake_cx.called("pptSign/stuSignajax")


# ------------------------------------------------------------- 普通 / 手势
def test_plain_sign_params(fake_cx, session):
    result = sign(session, make_activity(SignKind.PLAIN), SignOptions(name="张三"))
    assert result.ok

    p = fake_cx.last_params()
    assert p["activeId"] == "900001"
    assert p["uid"] == "400000000"
    assert p["fid"] == "10001"
    assert p["courseId"] == "200000000"
    assert p["classId"] == "300000000"
    assert p["name"] == "张三"
    assert p["appType"] == "15"
    assert p["latitude"] == "-1"
    assert p["longitude"] == "-1"


def test_gesture_uses_same_endpoint(fake_cx, session):
    result = sign(session, make_activity(SignKind.GESTURE), SignOptions(name="A"))
    assert result.ok
    assert fake_cx.last_params()["activeId"] == "900001"


def test_device_code_sent(fake_cx, session):
    sign(session, make_activity(SignKind.PLAIN), SignOptions(name="A", device_code="deadbeef" * 4))
    assert fake_cx.last_params()["deviceCode"] == "deadbeef" * 4


# ------------------------------------------------------------- 签到码
def test_signcode_passes_code(fake_cx, session):
    result = sign(session, make_activity(SignKind.SIGNCODE), SignOptions(name="A", sign_code="4821"))
    assert result.ok
    assert fake_cx.last_params()["signCode"] == "4821"


def test_signcode_skips_nonexistent_precheck(fake_cx, session):
    """checkSignCode 接口实测不存在，默认不该被调用。"""
    sign(session, make_activity(SignKind.SIGNCODE), SignOptions(name="A", sign_code="4821"))
    assert not fake_cx.called("checkSignCode")


# ------------------------------------------------------------- 位置
def test_location_params(fake_cx, session):
    result = sign(
        session,
        make_activity(SignKind.LOCATION),
        SignOptions(name="A", lat="34.817038", lon="113.516288", address="某某大学"),
    )
    assert result.ok

    p = fake_cx.last_params()
    assert p["ifTiJiao"] == "1"
    assert p["address"] == "某某大学"
    assert abs(float(p["latitude"]) - 34.817038) < 0.001
    assert abs(float(p["longitude"]) - 113.516288) < 0.001


def test_location_without_coords_refuses(fake_cx, session):
    result = sign(session, make_activity(SignKind.LOCATION), SignOptions(name="A"))
    assert not result.ok
    assert "经纬度" in result.message
    assert not fake_cx.called("pptSign/stuSignajax")


def test_location_distance_reported(fake_cx, session):
    fake_cx.set_reply("距离签到位置 512 米")
    result = sign(
        session,
        make_activity(SignKind.LOCATION),
        SignOptions(name="A", lat="34.0", lon="113.0", address="x"),
    )
    assert not result.ok
    assert "512" in result.message


# ------------------------------------------------------------- 二维码
def test_qrcode_passes_enc(fake_cx, session):
    result = sign(session, make_activity(SignKind.QRCODE), SignOptions(name="A", enc="1D0A628CK317"))
    assert result.ok
    assert fake_cx.last_params()["enc"] == "1D0A628CK317"


def test_qrcode_without_enc_refuses(fake_cx, session):
    result = sign(session, make_activity(SignKind.QRCODE), SignOptions(name="A"))
    assert not result.ok
    assert "enc" in result.message
    assert not fake_cx.called("pptSign/stuSignajax")


def test_qrcode_expired_reply(fake_cx, session):
    fake_cx.set_reply("签到失败，请重新扫描")
    result = sign(session, make_activity(SignKind.QRCODE), SignOptions(name="A", enc="OLD"))
    assert not result.ok
    assert "失效" in result.message


# ------------------------------------------------------------- 拍照
def test_photo_passes_object_id(fake_cx, session):
    result = sign(session, make_activity(SignKind.PHOTO), SignOptions(name="A", object_id="OBJ123"))
    assert result.ok
    assert fake_cx.last_params()["objectId"] == "OBJ123"


# ------------------------------------------------------------- 回执
@pytest.mark.parametrize(
    ("reply", "ok"),
    [("success", True), ("success2", True), ("fail", False), ("您已经签到过了", False)],
)
def test_reply_mapping(fake_cx, session, reply, ok):
    fake_cx.set_reply(reply)
    result = sign(session, make_activity(SignKind.PLAIN), SignOptions(name="A"))
    assert result.ok is ok


# ------------------------------------------------------------- 登录态
def test_logged_out_reply_raises(fake_cx, session):
    fake_cx.set_reply("请先登录再进行签到")
    with pytest.raises(AuthExpired):
        sign(session, make_activity(SignKind.PLAIN), SignOptions(name="A"))


def test_logged_out_redirect_raises(fake_cx, session):
    fake_cx.override(
        "pptSign/stuSignajax", 302, "",
        {"Location": "https://passport2.chaoxing.com/mlogin?refer=x"},
    )
    with pytest.raises(AuthExpired):
        sign(session, make_activity(SignKind.PLAIN), SignOptions(name="A"))


def test_mobile_error_redirect_raises(fake_cx, session):
    """preSign 的未登录跳转是 /widget/mobileError，不是 passport2 —— 最易漏。"""
    fake_cx.override(
        "newsign/preSign", 302, "",
        {"Location": "/widget/mobileError?errormsg=%E8%AF%B7%E7%99%BB%E5%BD%95"},
    )
    # run_chain 会吞掉异常，但 preSign 标记为 error
    sign(session, make_activity(SignKind.PLAIN), SignOptions(name="A"))


# ------------------------------------------------------------- 活动列表
def test_active_list_parsing(fake_cx, session):
    fake_cx.set_active_list(
        [
            {"id": 111, "nameOne": "签到", "otherId": 0, "ifphoto": 0, "status": 1, "startTime": 1},
            {"id": 222, "nameOne": "拍照", "otherId": 0, "ifphoto": 1, "status": 1, "startTime": 1},
            {"id": 333, "nameOne": "扫码", "otherId": 2, "status": 1, "startTime": 1},
            {"id": 444, "nameOne": "已结束", "otherId": 0, "status": 2, "startTime": 1},
        ]
    )
    activities = list_activities(session, COURSE)
    kinds = {a.active_id: a.kind for a in activities}
    assert kinds == {"111": SignKind.PLAIN, "222": SignKind.PHOTO, "333": SignKind.QRCODE}


def test_active_info_ifphoto_correction(fake_cx, session):
    fake_cx.set_active_info(otherId=0, ifphoto=1)
    info = get_active_info(session, "111")
    from cxsign.activity import classify

    assert classify(info) is SignKind.PHOTO


# ------------------------------------------------------------- 完整链路
def test_full_chain_all_six_kinds(fake_cx, session):
    """六种类型连打，全部成功，且每种都跑完了上报链。"""
    cases = [
        (SignKind.PLAIN, SignOptions(name="A")),
        (SignKind.GESTURE, SignOptions(name="A")),
        (SignKind.SIGNCODE, SignOptions(name="A", sign_code="1234")),
        (SignKind.LOCATION, SignOptions(name="A", lat="34.8", lon="113.5", address="校门")),
        (SignKind.PHOTO, SignOptions(name="A", object_id="OBJ")),
        (SignKind.QRCODE, SignOptions(name="A", enc="ENC")),
    ]
    for idx, (kind, opts) in enumerate(cases):
        fake_cx.reset()
        result = sign(session, make_activity(kind, active_id=f"act{idx}"), opts)
        assert result.ok, f"{kind} 失败：{result.message}"
        assert fake_cx.called("pptSign/analysis2"), f"{kind} 没跑上报链"
        assert fake_cx.last_params()["activeId"] == f"act{idx}"


def test_parse_reply_distance_helper():
    ok, msg = parse_reply("距离签到位置 12.7 米")
    assert not ok
    assert "12.7" in msg or "距离" in msg
