"""签到分发器：`Activity` + `SignOptions` → `SignResult`。

调用方只需：

    result = sign(session, activity, SignOptions(name="张三", lat="34.81", lon="113.51"))
    if not result.ok and result.kind is SignKind.QRCODE:
        ... 提示补 enc
"""

from __future__ import annotations

from .. import presign
from ..activity import Activity, SignKind
from ..config import Settings
from ..net import Session
from .base import SignOptions, SignResult
from .general import check_sign_code, sign_general, sign_signcode
from .location import configure_jitter, sign_location
from .photo import sign_photo, upload_photo
from .qrcode import extract_enc, sign_qrcode

__all__ = [
    "SignOptions",
    "SignResult",
    "sign",
    "check_sign_code",
    "upload_photo",
    "extract_enc",
    "configure_jitter",
]


def sign(
    session: Session,
    activity: Activity,
    options: SignOptions | None = None,
    *,
    settings: Settings | None = None,
    skip_presign: bool = False,
) -> SignResult:
    """执行一次签到。"""
    opts = options or SignOptions()
    if settings is not None:
        configure_jitter(settings.location_jitter_m)
        if opts.lat in ("", "-1") and settings.default_lat not in ("", "-1"):
            opts.lat = settings.default_lat
            opts.lon = settings.default_lon
            opts.address = opts.address or settings.default_address

    if not skip_presign:
        presign.run_chain(session, activity.active_id, activity.course)

    match activity.kind:
        case SignKind.PLAIN:
            return sign_general(session, activity, opts, kind=SignKind.PLAIN)
        case SignKind.GESTURE:
            return sign_general(session, activity, opts, kind=SignKind.GESTURE)
        case SignKind.SIGNCODE:
            return sign_signcode(session, activity, opts)
        case SignKind.LOCATION:
            return sign_location(session, activity, opts)
        case SignKind.PHOTO:
            return sign_photo(session, activity, opts)
        case SignKind.QRCODE:
            return sign_qrcode(session, activity, opts)
        case SignKind.FACE:
            return SignResult(
                ok=False,
                kind=SignKind.FACE,
                message="人脸签到需要已采集人脸并通过活体协议，本项目不在自动流程内处理",
            )
        case _:
            return SignResult(ok=False, kind=SignKind.UNKNOWN, message="未知签到类型，跳过")
