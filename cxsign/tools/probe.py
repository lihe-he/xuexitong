"""接口存在性探测：不登录也能区分"路径存在 / 不存在"。

判据：

* 302 跳 passport2 / mlogin / wlogin / mobileError → 路径存在，需要登录
* 200 + 业务内容                                 → 路径存在
* 500 + ``tengine`` 字样                         → **路径不存在**（网关兜底错误页）
* 404 / 405                                      → 路径不存在或方法不对

协议改版后第一件事就是跑这个，确认哪些 URL 还活着。
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import httpx

from ..config import DEFAULT_UA

TARGETS = [
    ("stuSignajax", "GET", "https://mobilelearn.chaoxing.com/pptSign/stuSignajax",
     {"activeId": "1", "uid": "1", "fid": "0"}),
    ("checkSignCode", "GET", "https://mobilelearn.chaoxing.com/pptSign/stu/checkSignCode",
     {"activeId": "1", "signCode": "1234"}),
    ("analysis", "GET", "https://mobilelearn.chaoxing.com/pptSign/analysis",
     {"vs": "1", "DB_STRATEGY": "RANDOM", "aid": "1"}),
    ("analysis2", "GET", "https://mobilelearn.chaoxing.com/pptSign/analysis2",
     {"DB_STRATEGY": "RANDOM", "code": "X"}),
    ("preSign", "GET", "https://mobilelearn.chaoxing.com/newsign/preSign",
     {"courseId": "1", "classId": "1", "activePrimaryId": "1", "general": "1",
      "sys": "1", "ls": "1", "appType": "15", "uid": "1", "ut": "s"}),
    ("activelist", "GET", "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist",
     {"fid": "0", "courseId": "1", "classId": "1", "_": "1"}),
    ("getPPTActiveInfo", "GET", "https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo",
     {"activeId": "1"}),
    ("sign/preStuSign", "GET", "https://mobilelearn.chaoxing.com/sign/preStuSign",
     {"activeId": "1", "uid": "1", "classId": "0", "general": "0", "appType": "0", "sys": "0"}),
    ("sign/stuSignajax", "GET", "https://mobilelearn.chaoxing.com/sign/stuSignajax",
     {"activeId": "1", "uid": "1", "clientip": ""}),
    ("pan token", "GET", "https://pan-yz.chaoxing.com/api/token/uservalid", None),
    ("webim/me", "GET", "https://im.chaoxing.com/webim/me", None),
]

#: 二维码相关：验证"凭 activeId 换 enc"的接口是否存在
QR_TARGETS = [
    (name, "GET", f"https://mobilelearn.chaoxing.com{path}", {"activeId": "1"})
    for name, path in [
        ("getQrCode", "/pptSign/getQrCode"),
        ("getQRCode", "/pptSign/getQRCode"),
        ("pptSign/qrcode", "/pptSign/qrcode"),
        ("stu/getEnc", "/pptSign/stu/getEnc"),
        ("getEnc", "/pptSign/getEnc"),
        ("newsign/getEnc", "/newsign/getEnc"),
        ("newsign/qrcode", "/newsign/qrcode"),
        ("api/getQRCode", "/v2/apis/active/getQRCode"),
        ("api/getQrCode", "/v2/apis/active/getQrCode"),
        ("stu/qrcode", "/pptSign/stu/qrcode"),
    ]
]


@dataclass
class Probe:
    name: str
    status: int
    location: str
    body: str

    @property
    def verdict(self) -> str:
        if self.status == 500 and "tengine" in self.body:
            return "不存在"
        if self.status in (404, 405):
            return "不存在"
        low = self.location.lower()
        if any(k in low for k in ("passport2", "mlogin", "wlogin", "mobileerror")):
            return "存在·需登录"
        if self.status == 200 and self.body.strip():
            return "存在·有返回"
        if self.status in (301, 302, 307, 308):
            return "存在·跳转"
        return f"未知({self.status})"


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    cases = QR_TARGETS if args.qr else TARGETS
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://mobilelearn.chaoxing.com/",
    }

    rows: list[Probe] = []
    with httpx.Client(timeout=12, follow_redirects=False, headers=headers) as client:
        for name, method, url, params in cases:
            try:
                resp = client.request(method, url, params=params)
                rows.append(
                    Probe(
                        name=name,
                        status=resp.status_code,
                        location=resp.headers.get("location", ""),
                        body=resp.text[:200],
                    )
                )
            except httpx.HTTPError as exc:
                rows.append(Probe(name=name, status=-1, location="", body=str(exc)[:80]))
            time.sleep(1.2)

    width = max(len(r.name) for r in rows)
    for r in rows:
        print(f"{r.name:<{width}}  {r.status:<4} {r.verdict:<14} {r.location[:56]}")
        print(f"{'':<{width}}  body: {r.body[:70].replace(chr(10), ' ')}")
    return 0
