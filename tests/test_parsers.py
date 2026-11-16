"""真实页面结构的解析回归测试。

HTML 片段按 2026-11 生产环境的结构精简而来（去掉无关节点，保留所有被解析的属性）。
"""

from __future__ import annotations

import pytest

from cxsign.auth import _NAME_RE3, _NAME_RE4
from cxsign.course import parse_course_html

COURSE_HTML = """
<div class="course clearfix  learnCourse stu_300000000" info="300000000_900000000"
     roleId="stu_300000000" id="c_200000000" >
    <div class="course-cover">
        <input type="hidden" class="clazzId" name="clazzId" value="300000000"/>
        <input type="hidden" class="courseId" name="courseId" value="200000000"/>
        <input type="hidden" class="role" name="role" value="0"/>
        <input type="hidden" class="curPersonId"  value="900000000"/>
    </div>
    <div class="course-info">
        <h3 class="inlineBlock">
            <a class="color1" href="https://mooc1.chaoxing.com/visit/stucoursemiddle?courseid=200000000">
                <span class="course-name overHidden2" style="word-break: break-all;"
                      title="（2026秋）形势与政策1.3.5">（2026秋）形势与政策1.3.5</span>
                <i class="icon-news"></i>
            </a>
        </h3>
        <p class="margint10 line2 color2" title="某某大学">某某大学</p>
        <p class="line2 color3" title="李老师">李老师</p>
    </div>
</div>
<div class="course clearfix  learnCourse stu_151518151" info="151518151_900000000"
     roleId="stu_151518151" id="c_265930770" >
    <div class="course-cover">
        <input type="hidden" class="clazzId" name="clazzId" value="151518151"/>
        <input type="hidden" class="courseId" name="courseId" value="265930770"/>
    </div>
    <div class="course-info">
        <h3 class="inlineBlock">
            <a class="color1" href="https://mooc1.chaoxing.com/visit/stucoursemiddle?courseid=265930770">
                <span class="course-name overHidden2" style="word-break: break-all;"
                      title="面向对象程序设计">面向对象程序设计</span>
            </a>
        </h3>
        <p class="margint10 line2 color2" title="某某大学">某某大学</p>
        <p class="line2 color3" title="王老师">王老师</p>
    </div>
</div>
"""

ACCOUNT_HTML = """
<div class="setUl">
    <ul>
        <li>
            <!--与后端修改姓名规则一致-->
            <p class="fr colorBlue">
                张三
            </p>姓名
        </li>
        <li onclick="openUrl('/mooc/accountManage?field=phone&showBar=1')">
            <p class="fr color999"><i class="arrowRight fr"></i>152****9912</p>手机号
        </li>
    </ul>
    <ul>
        <li onclick="openUrl('/mooc/accountManage?field=company&showBar=1')">
            <p class="fr color999"><i class="arrowRight fr"></i>
                某某大学
            </p>单位设置
        </li>
        <li onclick="openUrl('https://authen.chaoxing.com/authsign/show?certifyType=4')">
            <p class="fr color999"><i class="arrowRight fr"></i>张三（已认证）</p>
            实名认证
        </li>
    </ul>
</div>
"""


# ------------------------------------------------------------------ 课程
def test_parse_course_html_counts():
    courses = parse_course_html(COURSE_HTML)
    assert len(courses) == 2


def test_parse_course_html_fields():
    c = parse_course_html(COURSE_HTML)[0]
    assert c.course_id == "200000000"
    assert c.class_id == "300000000"
    assert c.name == "（2026秋）形势与政策1.3.5"
    assert c.school == "某某大学"
    assert c.teacher == "李老师"


def test_parse_course_html_keeps_pairing():
    """块内切分的关键收益：courseId 和 classId 不会跨课程错配。"""
    courses = parse_course_html(COURSE_HTML)
    assert courses[1].course_id == "265930770"
    assert courses[1].class_id == "151518151"
    assert courses[1].name == "面向对象程序设计"
    # 确认没有把第一门的 classId 配到第二门
    assert courses[1].class_id != courses[0].class_id


def test_parse_course_html_empty():
    assert parse_course_html("") == []
    assert parse_course_html("<div>没有课程</div>") == []


def test_parse_course_html_fallback_ids():
    """老页面没有 course-name，只有 course_xx_yy。"""
    html = '<div id="course_111_222" class="x"></div>'
    courses = parse_course_html(html)
    assert len(courses) == 1
    assert courses[0].course_id == "111"
    assert courses[0].class_id == "222"


def test_parse_course_html_dedup():
    assert len(parse_course_html(COURSE_HTML + COURSE_HTML)) == 2


# ------------------------------------------------------------------ 姓名
def test_name_from_colorblue_row():
    m = _NAME_RE3.search(ACCOUNT_HTML)
    assert m is not None
    assert m.group(1).strip() == "张三"


def test_name_from_certified_row():
    m = _NAME_RE4.search(ACCOUNT_HTML)
    assert m is not None
    assert m.group(1).strip() == "张三"


def test_name_patterns_do_not_match_noise():
    assert _NAME_RE3.search("<html>请登录</html>") is None
    assert _NAME_RE4.search("<html>请登录</html>") is None


def test_name_pattern_handles_whitespace():
    html = '<p class="fr colorBlue">\n   张三 \n</p>姓名'
    assert _NAME_RE3.search(html).group(1).strip() == "张三"


# ------------------------------------------------------------------ 其它
@pytest.mark.parametrize(
    "raw",
    [
        "_uid=1; vc3=abc; fid=2",
        "Cookie: _uid=1; vc3=abc; fid=2",
        '{"_uid":"1","vc3":"abc","fid":"2"}',
    ],
)
def test_parse_cookies_keeps_vc3(raw):
    from cxsign.course import parse_cookies

    assert parse_cookies(raw)["vc3"] == "abc"


def test_course_str():
    from cxsign.course import Course

    c = Course("1", "2", "数据结构")
    assert str(c) == "数据结构(2)"
    assert str(Course("1", "2")) == "1(2)"
