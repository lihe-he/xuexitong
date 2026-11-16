"""活动列表、活动详情、签到类型判定。

## 类型判定是第一优先级的事

学习通用两个字段描述签到类型，含义随端不同：

``otherId``（activelist / getPPTActiveInfo 都有）
    0 普通（**若 ``ifphoto == 1`` 则为拍照**）
    2 二维码
    3 手势
    4 位置
    5 签到码

``activeSort``（新版 getPPTActiveInfo 才完整）
    5 人脸
    6 二维码
    7 二维码（约 30s 轮换）
    8 二维码 + 指定地点
    9 签到码

判定顺序：``otherId`` 命中已知值就用它；否则退回 ``activeSort``。
``otherId == 0`` 时必须再读 ``ifphoto``，这是新手最常翻车的地方。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from . import endpoints
from .course import Course
from .net import ApiError, Session, TooFrequent


class SignKind(StrEnum):
    PLAIN = "plain"        # 普通签到
    GESTURE = "gesture"    # 手势签到
    LOCATION = "location"  # 位置签到
    PHOTO = "photo"        # 拍照签到
    QRCODE = "qrcode"      # 二维码签到
    SIGNCODE = "signcode"  # 签到码签到
    FACE = "face"          # 人脸签到（需已采集人脸）
    UNKNOWN = "unknown"


#: 需要外部输入才能完成的类型
NEED_INPUT: dict[SignKind, str] = {
    SignKind.QRCODE: "enc",     # 二维码里解析出的 enc
    SignKind.SIGNCODE: "code",  # 老师口头念的签到码
    SignKind.FACE: "face",      # 未采集人脸则无法完成
}

_OTHER_ID_MAP = {
    0: SignKind.PLAIN,
    2: SignKind.QRCODE,
    3: SignKind.GESTURE,
    4: SignKind.LOCATION,
    5: SignKind.SIGNCODE,
}

_ACTIVE_SORT_MAP = {
    5: SignKind.FACE,
    6: SignKind.QRCODE,
    7: SignKind.QRCODE,
    8: SignKind.QRCODE,
    9: SignKind.SIGNCODE,
}

#: 未登录时的 errorMsg 关键词（getPPTActiveInfo / activelist 共用）
_LOGGED_OUT_HINTS = ("未登录", "未登陆", "请登录", "登录")


def is_logged_out_payload(data: Any) -> bool:
    """学习通有些接口未登录时返回 **200 + result:0**，不是 302。

    实测 ``getPPTActiveInfo`` 返回::

        {"result": 0, "msg": null, "data": null, "errorMsg": "未登录或其他"}

    这类必须单独识别，否则会被当成"接口异常"而不是"该重新登录了"。
    """
    if not isinstance(data, dict):
        return False
    try:
        result = int(data.get("result", 1))
    except (TypeError, ValueError):
        return False
    if result == 1:
        return False
    err = str(data.get("errorMsg") or data.get("msg") or "")
    return any(h in err for h in _LOGGED_OUT_HINTS)


def check_logged_in(data: Any) -> None:
    """未登录就抛 AuthExpired，把重登逻辑交给上层。"""
    from .net import AuthExpired

    if is_logged_out_payload(data):
        raise AuthExpired(f"接口返回未登录：{(data or {}).get('errorMsg') or ''}")


@dataclass(slots=True)
class Activity:
    """一条待签到活动。"""

    active_id: str
    name: str
    course: Course
    kind: SignKind
    status: int = 1
    start_time: int = 0
    end_time: int = 0
    other_id: int = -1
    active_sort: int = -1
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        if not self.start_time:
            return 0.0
        ts = self.start_time / 1000 if self.start_time > 10**12 else self.start_time
        return time.time() - ts

    @property
    def needs_input(self) -> str | None:
        return NEED_INPUT.get(self.kind)

    def __str__(self) -> str:
        return f"[{self.course}] {self.name} <{self.kind.value}> active={self.active_id}"


def classify(info: dict[str, Any]) -> SignKind:
    """从活动 JSON 判定签到类型。"""
    try:
        other_id = int(info.get("otherId", -1))
    except (TypeError, ValueError):
        other_id = -1

    kind = _OTHER_ID_MAP.get(other_id, SignKind.UNKNOWN)
    if other_id == 0:
        # 关键分支：otherId=0 既可能是普通，也可能是拍照
        try:
            kind = SignKind.PHOTO if int(info.get("ifphoto", 0) or 0) == 1 else SignKind.PLAIN
        except (TypeError, ValueError):
            kind = SignKind.PLAIN

    if kind is SignKind.UNKNOWN:
        try:
            active_sort = int(info.get("activeSort", -1))
        except (TypeError, ValueError):
            active_sort = -1
        kind = _ACTIVE_SORT_MAP.get(active_sort, SignKind.UNKNOWN)

    return kind


def list_activities(
    session: Session,
    course: Course,
    *,
    fid: str | None = None,
    include_not_started: bool = False,
) -> list[Activity]:
    """拉某门课的进行中活动。返回空列表表示"确实没有"，抛 TooFrequent 表示"请求太频"。"""
    params = {
        "fid": fid or session.fid,
        "courseId": course.course_id,
        "classId": course.class_id,
        "showNotStartedActive": 1 if include_not_started else 0,
        "_": str(int(time.time() * 1000)),
    }
    data = session.get_json(endpoints.ACTIVE_LIST, params=params)
    if data is None:
        raise TooFrequent(f"activelist 返回空：{course}")
    check_logged_in(data)

    # data: {"result":1,"data":{"activeList":[...]}} 或 {"result":1,"data":null}
    inner = data.get("data") if isinstance(data, dict) else None
    if inner is None:
        raise TooFrequent(f"activelist data 为 null：{course}")

    out: list[Activity] = []
    for item in inner.get("activeList") or []:
        try:
            status = int(item.get("status", 0))
            other_id = int(item.get("otherId", -1))
        except (TypeError, ValueError):
            status, other_id = 0, -1
        # 只要进行中的签到（otherId 0~5）
        if status != 1 or not (0 <= other_id <= 5):
            continue
        out.append(
            Activity(
                active_id=str(item.get("id") or item.get("activeId") or ""),
                name=str(item.get("nameOne") or item.get("name") or ""),
                course=course,
                kind=classify(item),
                status=status,
                start_time=int(item.get("startTime") or 0),
                end_time=int(item.get("endTime") or 0),
                other_id=other_id,
                active_sort=int(item.get("activeSort") or -1),
                raw=item,
            )
        )
    return out


def get_active_info(session: Session, active_id: str) -> dict[str, Any]:
    """活动详情。拍照签到必须调这个看 ``ifphoto``。"""
    data = session.get_json(endpoints.ACTIVE_INFO, params={"activeId": active_id})
    check_logged_in(data)
    if not isinstance(data, dict) or data.get("data") is None:
        raise ApiError(f"getPPTActiveInfo 异常：{str(data)[:200]}")
    return data["data"]


def describe(kind: SignKind) -> str:
    return {
        SignKind.PLAIN: "普通签到",
        SignKind.GESTURE: "手势签到",
        SignKind.LOCATION: "位置签到",
        SignKind.PHOTO: "拍照签到",
        SignKind.QRCODE: "二维码签到",
        SignKind.SIGNCODE: "签到码签到",
        SignKind.FACE: "人脸签到",
        SignKind.UNKNOWN: "未知类型",
    }[kind]
