"""拍照签到。

流程：
1. 上传照片到超星云盘 ``pan-yz.chaoxing.com``，拿到 ``objectId``
2. 带 ``objectId`` 调 ``stuSignajax``

云盘上传需要 ``_token``，从 ``/api/token/uservalid`` 取。
也可以手工把图传到网盘根目录命名为 ``0.jpg``，然后只查列表（cxOrz 的做法），
本项目两种都支持。
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import endpoints
from ..activity import Activity, SignKind
from ..net import ApiError, Session
from .base import SignOptions, SignResult, base_params, submit


def get_pan_token(session: Session) -> str:
    resp = session.get(endpoints.PAN_TOKEN)
    text = (resp.text or "").strip()
    if not text:
        raise ApiError("获取云盘 token 失败（返回空）")
    return text


def get_root_dir(session: Session) -> tuple[str, str]:
    """从云盘首页 HTML 里抠出 ``enc`` 和 ``_rootdir``（parentId）。"""
    resp = session.get(endpoints.PAN_HOME)
    html = resp.text or ""

    m_enc = re.search(r'enc\s*=\s*"([^"]+)"', html)
    m_root = re.search(r'_rootdir\s*=\s*"([^"]+)"', html)
    if not m_enc or not m_root:
        raise ApiError("解析云盘首页失败，enc / _rootdir 未找到")
    return m_enc.group(1), m_root.group(1)


def list_pan_files(session: Session, page: int = 1, size: int = 50) -> list[dict]:
    enc, parent_id = get_root_dir(session)
    form = {
        "puid": "0",
        "shareid": "0",
        "parentId": parent_id,
        "page": str(page),
        "size": str(size),
        "enc": enc,
    }
    resp = session.post(
        endpoints.PAN_LIST,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(f"云盘列表返回非 JSON：{resp.text[:200]}") from exc
    return data.get("list") or []


def find_uploaded_object_id(session: Session, names: tuple[str, ...] = ("0.jpg", "0.png")) -> str:
    """在云盘根目录里找指定文件名的照片，返回 objectId。"""
    for item in list_pan_files(session):
        if item.get("name") in names:
            return str(item.get("objectId") or "")
    return ""


def upload_photo(session: Session, image_path: str | Path) -> str:
    """上传本地图片，返回 objectId。"""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在：{path}")

    token = get_pan_token(session)
    suffix = path.suffix.lower() or ".jpg"
    content = path.read_bytes()

    files = {"file": (f"1{suffix}", content, "image/jpeg" if suffix != ".png" else "image/png")}
    form = {"puid": session.uid}
    resp = session.post(
        f"{endpoints.PAN_UPLOAD}?_from=mobilelearn&_token={token}",
        data=form,
        files=files,
    )
    text = (resp.text or "").strip()
    if not text:
        raise ApiError("云盘上传返回空")
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        # 有的版本返回纯 objectId 字符串
        return text.strip('"')

    return str(data.get("objectId") or data.get("objectid") or "")


def resolve_object_id(session: Session, opts: SignOptions) -> str:
    """按优先级拿 objectId：显式指定 > 本地图片上传 > 云盘扫码。"""
    if opts.object_id:
        return opts.object_id
    local = opts.extra.get("photo_path")
    if local:
        return upload_photo(session, local)
    return find_uploaded_object_id(session)


def sign_photo(session: Session, activity: Activity, opts: SignOptions) -> SignResult:
    try:
        object_id = resolve_object_id(session, opts)
    except Exception as exc:  # noqa: BLE001
        return SignResult(
            ok=False, kind=SignKind.PHOTO, message=f"获取 objectId 失败：{exc}"
        )
    if not object_id:
        return SignResult(
            ok=False,
            kind=SignKind.PHOTO,
            message="云盘里没有 0.jpg/0.png，也没有指定本地图片",
        )

    params = base_params(session, activity, opts)
    params.update(
        {
            "objectId": object_id,
            "latitude": "-1",
            "longitude": "-1",
        }
    )
    ok, msg, url = submit(session, params)
    return SignResult(ok=ok, message=msg, kind=SignKind.PHOTO, raw=msg, request_url=url)
