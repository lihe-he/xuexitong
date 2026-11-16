"""群聊签到（无课程的活动）。

学习通除了"课程活动"，还有从班级群/聊天群直接发起的签到，走另一套接口：

    sign/preStuSign  → 登记
    sign/stuSignajax → 提交

参数里 ``chatId`` / ``tid`` 来自群消息，适合做"班群"场景。
"""

from __future__ import annotations

from . import endpoints
from .net import Session
from .signer.base import parse_reply


def pre_sign_chat(
    session: Session,
    activity_id: str,
    *,
    chat_id: str = "",
    tid: str = "",
) -> str:
    resp = session.get(
        endpoints.CHAT_PRE_SIGN,
        params={
            "activeId": activity_id,
            "code": "",
            "uid": session.uid,
            "courseId": "null",
            "classId": "0",
            "general": "0",
            "chatId": chat_id,
            "appType": "0",
            "tid": tid,
            "atype": "null",
            "sys": "0",
        },
    )
    return resp.text


def sign_chat(
    session: Session,
    activity_id: str,
    *,
    chat_id: str = "",
    tid: str = "",
    lat: str = "-1",
    lon: str = "-1",
    address: str = "",
    object_id: str = "",
) -> tuple[bool, str]:
    pre_sign_chat(session, activity_id, chat_id=chat_id, tid=tid)

    params: dict[str, str] = {
        "activeId": activity_id,
        "uid": session.uid,
        "clientip": "",
        "latitude": lat,
        "longitude": lon,
        "fid": "0",
    }
    if address:
        params["address"] = address
        params["ifTiJiao"] = "1"
    if object_id:
        params["objectId"] = object_id

    method = "POST" if address else "GET"
    if method == "POST":
        resp = session.post(endpoints.CHAT_SIGN_AJAX, data=params)
    else:
        resp = session.get(endpoints.CHAT_SIGN_AJAX, params=params)
    return parse_reply(resp.text)
