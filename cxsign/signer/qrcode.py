"""二维码签到。

二维码签到是这套协议里**唯一无法纯服务端解决**的类型：``enc`` 只存在于老师
屏幕上的动态二维码里，通常 30 秒轮换，且有时绑定指定地点。

可行路径（按工程成本排序）：

1. 人工提供 enc —— 手机扫一下，把 ``enc=`` 后面的值贴进来（最常用）
2. 图片 OCR —— 截屏 + 识别二维码，拿到 enc（部分项目用腾讯云 OCR）
3. 监听老师端接口 —— 需要教师权限，不现实
4. 改包伪造活动 —— 已经越过"签到"范畴，本项目不做

``enc`` 形如 ``1D0A628CK317F44CCC378M5KD92``，从二维码解码结果里取。
"""

from __future__ import annotations

import json

from ..activity import Activity, SignKind
from ..net import Session
from .base import SignOptions, SignResult, base_params, submit


def build_location_payload(lat: str, lon: str, address: str, altitude: str = "100") -> str:
    """二维码签到要求把位置塞进一个 JSON 字符串参数 ``location``。"""
    return json.dumps(
        {
            "result": "1",
            "address": address,
            "latitude": float(lat) if lat not in ("", "-1") else -1,
            "longitude": float(lon) if lon not in ("", "-1") else -1,
            "altitude": float(altitude or 100),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def sign_qrcode(session: Session, activity: Activity, opts: SignOptions) -> SignResult:
    if not opts.enc:
        return SignResult(
            ok=False,
            kind=SignKind.QRCODE,
            message="缺少 enc —— 请扫码获取二维码里的 enc 参数后重试",
        )

    params = base_params(session, activity, opts)
    params["enc"] = opts.enc
    if opts.lat not in ("", "-1") and opts.lon not in ("", "-1"):
        params["location"] = build_location_payload(opts.lat, opts.lon, opts.address, opts.altitude)
    params.update({"latitude": "-1", "longitude": "-1"})

    ok, msg, url = submit(session, params)
    return SignResult(ok=ok, message=msg, kind=SignKind.QRCODE, raw=msg, request_url=url)


def extract_enc(qr_text: str) -> str:
    """从二维码解码文本里抠出 enc。

    常见形式：
        http://mobilelearn.chaoxing.com/newsign/xxx?enc=1D0A628CK...
        enc=1D0A628CK...&...
        直接就是一串 enc
    """
    text = (qr_text or "").strip()
    if not text:
        return ""
    if "enc=" in text:
        seg = text.split("enc=", 1)[1]
        for sep in ("&", "#", " "):
            seg = seg.split(sep, 1)[0]
        return seg.strip()
    if "/" not in text and " " not in text:
        return text
    return ""
