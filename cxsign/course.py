"""课程列表。

真实页面结构（2026-11，mooc2-ans 版）::

    <div class="course clearfix  learnCourse stu_300000000"
         info="300000000_900000000" roleId="stu_300000000"
         id="c_200000000">
      <input type="hidden" class="clazzId"  name="clazzId"  value="300000000"/>
      <input type="hidden" class="courseId" name="courseId" value="200000000"/>
      <input type="hidden" class="curPersonId" value="900000000"/>
      ...
      <span class="course-name overHidden2" ... title="（2026秋）形势与政策1.3.5">
          （2026秋）形势与政策1.3.5</span>
      <p class="margint10 line2 color2" title="某某大学">某某大学</p>
      <p class="line2 color3" title="李老师">李老师</p>
    </div>

三个 id 都在同一块里，所以按块切分比全局正则可靠得多
（全局正则会把课程的 classId 和下一门课的 courseId 配到一起）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import endpoints
from .net import Session

_BLOCK_SPLIT = re.compile(r'(?=<div class="course clearfix)')
_ID_RE = re.compile(r'id="c_(\d+)"')
_ROLE_RE = re.compile(r'roleId="stu_(\d+)"')
_CLAZZ_INPUT_RE = re.compile(r'class="clazzId"[^>]*value="(\d+)"')
_COURSE_INPUT_RE = re.compile(r'class="courseId"[^>]*value="(\d+)"')
_NAME_RE = re.compile(r'class="course-name[^"]*"[^>]*title="([^"]*)"')
_SCHOOL_RE = re.compile(r'class="margint10 line2 color2"[^>]*title="([^"]*)"')
_TEACHER_RE = re.compile(r'class="line2 color3"[^>]*title="([^"]*)"')

#: 兜底：老版本页面没有 course-name，靠 course_xx_yy 抓 ID
_COURSE_RE = re.compile(r"course_(\d+)_(\d+)")
_COURSE_JSON_RE = re.compile(r'"courseid"\s*:\s*"?(\d+)"?[^}]*?"clazzid"\s*:\s*"?(\d+)"?')


@dataclass(slots=True, frozen=True)
class Course:
    course_id: str
    class_id: str
    name: str = ""
    school: str = ""
    teacher: str = ""

    def __str__(self) -> str:
        return f"{self.name or self.course_id}({self.class_id})"


def parse_course_html(html: str) -> list[Course]:
    """从 courselistdata 的 HTML 片段里解析课程。"""
    courses: list[Course] = []
    seen: set[tuple[str, str]] = set()

    for chunk in _BLOCK_SPLIT.split(html or ""):
        if not chunk.startswith('<div class="course clearfix'):
            continue

        course_id = ""
        m = _ID_RE.search(chunk) or _COURSE_INPUT_RE.search(chunk)
        if m:
            course_id = m.group(1)

        class_id = ""
        m = _ROLE_RE.search(chunk) or _CLAZZ_INPUT_RE.search(chunk)
        if m:
            class_id = m.group(1)

        if not (course_id and class_id):
            continue

        key = (course_id, class_id)
        if key in seen:
            continue
        seen.add(key)

        name = _NAME_RE.search(chunk)
        school = _SCHOOL_RE.search(chunk)
        teacher = _TEACHER_RE.search(chunk)
        courses.append(
            Course(
                course_id=course_id,
                class_id=class_id,
                name=name.group(1).strip() if name else "",
                school=school.group(1).strip() if school else "",
                teacher=teacher.group(1).strip() if teacher else "",
            )
        )

    if courses:
        return courses

    # 兜底：更老的页面只有 course_id_classId
    for m in _COURSE_RE.finditer(html or ""):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            courses.append(Course(course_id=key[0], class_id=key[1]))
    return courses


def list_courses(session: Session) -> list[Course]:
    """返回去重后的课程列表（带课程名）。"""
    for url in (endpoints.COURSE_LIST, endpoints.COURSE_LIST_ALT):
        try:
            resp = session.post(
                url,
                data={"courseType": "1", "courseFolderId": "0", "courseFolderSize": "0"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": (
                        "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
                        "?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans"
                    ),
                },
            )
        except Exception:  # noqa: BLE001 —— 一个入口挂了换另一个
            continue
        if resp.status_code >= 400 or not resp.text:
            continue

        courses = parse_course_html(resp.text)
        if courses:
            return courses

    return []


def parse_course_json(text: str) -> list[Course]:
    """从 backclazzdata 之类的 JSON 文本里抽课程（备用路径）。"""
    out: list[Course] = []
    seen: set[tuple[str, str]] = set()
    for m in _COURSE_JSON_RE.finditer(text):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            out.append(Course(course_id=key[0], class_id=key[1]))
    return out


#: 从浏览器/客户端导出的 Cookie 里真正需要的字段
_COOKIE_WANTED = ("_uid", "UID", "fid", "_d", "vc3", "uf", "lv", "uf_")


def parse_cookies(raw: str | dict[str, str]) -> dict[str, str]:
    """把各种形态的 Cookie 归一成 dict。

    支持：

    * 浏览器 DevTools 的请求头：``_uid=123; fid=456; _d=xxx``
    * 直接粘贴的 JSON：``{"_uid": "123", "fid": "456"}``
    * 已经解析好的 dict
    * 带 ``Cookie:`` 前缀的整行
    """
    import json

    if isinstance(raw, dict):
        items = {str(k).strip(): str(v).strip() for k, v in raw.items()}
    else:
        text = (raw or "").strip()
        if text.lower().startswith("cookie:"):
            text = text[7:].strip()
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Cookie JSON 解析失败：{exc}") from exc
            items = {str(k).strip(): str(v).strip() for k, v in data.items()}
        else:
            items = {}
            for part in text.replace("\n", ";").split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                key, _, value = part.partition("=")
                items[key.strip()] = value.strip()

    # 丢掉明显无关的项（比如 _blank、t），但保留未知字段，它们可能有用于签名
    return {k: v for k, v in items.items() if k and v and k.lower() not in ("t", "_blank", "refer")}
