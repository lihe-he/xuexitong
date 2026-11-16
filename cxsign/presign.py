"""签到前的反作弊上报链。

真实 H5 页面在提交 `stuSignajax` 之前一定会先跑完这三步：

    1. GET newsign/preSign           → 登记"我要签到了"
    2. GET pptSign/analysis          → 返回一段 JS，里面藏着一个 code
    3. GET pptSign/analysis2?code=   → 上报这个 code

跳过这段，签到请求可能返回 success 但**不计入**，或者直接被判作弊。
这是很多 simpl 实现里最大的坑，所以单独成模块。
"""

from __future__ import annotations

import re
import time

from . import endpoints
from .course import Course
from .net import Session

_CODE_RE = re.compile(r"code\s*=\s*'\+?'([0-9A-Za-z]+)'")

#: analysis2 之后等待的毫秒数，用于对齐真实 H5 行为（测试里会置 0）
SUBMIT_DELAY = 0.5

#: 实测 analysis 返回的完整形态（2026-11）：
#: $.ajax({type:'get',url:'/pptSign/analysis2?DB_STRATEGY=RANDOM&code='+'a739c0d2...',success:function(res){}});
_SAMPLE = (
    "$.ajax({type:'get',url:'/pptSign/analysis2?DB_STRATEGY=RANDOM&code='+'{}'"
    ",success:function(res){{}});"
)


def pre_sign(session: Session, activity_id: str, course: Course | None = None) -> str:
    """登记签到意图。返回 preSign 页面文本（部分活动页面里带 enc）。"""
    params = {
        "courseId": course.course_id if course else "",
        "classId": course.class_id if course else "",
        "activePrimaryId": activity_id,
        "general": "1",
        "sys": "1",
        "ls": "1",
        "appType": "15",
        "tid": "",
        "uid": session.uid,
        "ut": "s",
    }
    resp = session.get(endpoints.PRE_SIGN, params=params)
    return resp.text


def analysis(session: Session, activity_id: str) -> str:
    """第 2 步：取 code。返回空串表示页面结构变了（不致命，继续即可）。"""
    resp = session.get(
        endpoints.ANALYSIS,
        params={"vs": "1", "DB_STRATEGY": "RANDOM", "aid": activity_id},
    )
    text = resp.text
    m = _CODE_RE.search(text)
    if m:
        return m.group(1)
    # 页面结构变体：code='+'XXXX'
    idx = text.find("code='+'")
    if idx != -1:
        rest = text[idx + 8 :]
        end = rest.find("'")
        if end > 0:
            return rest[:end]
    return ""


def analysis2(session: Session, code: str) -> str:
    """第 3 步：上报 code。返回服务端原话，便于日志排查。"""
    resp = session.get(
        endpoints.ANALYSIS2,
        params={"DB_STRATEGY": "RANDOM", "code": code},
    )
    return resp.text.strip()


def run_chain(session: Session, activity_id: str, course: Course | None = None) -> dict[str, str]:
    """跑完整条上报链，返回每步结果。任何一步失败都不阻断签到，只记录。"""
    result: dict[str, str] = {}
    try:
        result["preSign"] = "ok" if pre_sign(session, activity_id, course) else "empty"
    except Exception as exc:  # noqa: BLE001
        result["preSign"] = f"error: {exc}"
        return result

    try:
        code = analysis(session, activity_id)
        result["code"] = code or "missing"
        if code:
            result["analysis2"] = analysis2(session, code)[:120] or "ok"
    except Exception as exc:  # noqa: BLE001
        result["analysis2"] = f"error: {exc}"

    # H5 页面在 analysis2 之后固定等 500ms 再提交
    if SUBMIT_DELAY > 0:
        time.sleep(SUBMIT_DELAY)
    return result
