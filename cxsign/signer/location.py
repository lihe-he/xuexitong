"""位置签到。

要点：
1. 坐标系是 **BD-09**（百度），传 WGS-84 会偏 500 米左右
2. 必须带 ``ifTiJiao=1``，否则服务端只返回距离不落库
3. 失败回执是「距离签到位置 X 米」，可以用它做单点校正
4. 同一坐标反复签同一门课很显眼，加 ``jitter`` 抖动
"""

from __future__ import annotations

import math
import random
import re

from ..activity import Activity, SignKind
from ..net import Session
from .base import SignOptions, SignResult, base_params, submit

#: 纬度 1 度 ≈ 111320 米
_M_PER_DEG = 111_320.0

#: 抖动半径（米），由 Settings.location_jitter_m 注入
_JITTER_RADIUS = 8.0


def configure_jitter(radius_m: float) -> None:
    global _JITTER_RADIUS
    _JITTER_RADIUS = max(0.0, float(radius_m))


def jitter(lat: float, lon: float, radius_m: float | None = None) -> tuple[str, str]:
    """在半径 radius_m 内随机偏移，返回保留 6 位小数的 (lat, lon)。"""
    radius = _JITTER_RADIUS if radius_m is None else max(0.0, float(radius_m))
    if radius <= 0:
        return f"{lat:.6f}", f"{lon:.6f}"

    dlat = random.uniform(-radius, radius) / _M_PER_DEG
    # 经度随纬度收缩：cos(0°)=1，cos(60°)=0.5
    scale = max(0.1, math.cos(math.radians(lat)))
    dlon = random.uniform(-radius, radius) / (_M_PER_DEG * scale)
    return f"{lat + dlat:.6f}", f"{lon + dlon:.6f}"


def sign_location(session: Session, activity: Activity, opts: SignOptions) -> SignResult:
    if opts.lat in ("", "-1") or opts.lon in ("", "-1"):
        return SignResult(
            ok=False,
            message="位置签到需要经纬度（BD-09），请在 config.toml 填 default_lat / default_lon",
            kind=SignKind.LOCATION,
        )

    try:
        lat, lon = jitter(float(opts.lat), float(opts.lon))
    except ValueError:
        lat, lon = str(opts.lat), str(opts.lon)

    params = base_params(session, activity, opts)
    params.update(
        {
            "latitude": lat,
            "longitude": lon,
            "address": opts.address,
            "ifTiJiao": "1",
        }
    )

    ok, msg, url = submit(session, params)
    if not ok:
        dist = location_distance(msg)
        if dist is not None:
            msg = f"{msg}（偏差 {dist} 米，核对 default_lat/lon 是否为 BD-09 坐标）"
    return SignResult(ok=ok, message=msg, kind=SignKind.LOCATION, raw=msg, request_url=url)


def location_distance(text: str) -> int | None:
    """从「距离签到位置 1234 米」里抽出距离，便于自动校正。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*米", text or "")
    return int(float(m.group(1))) if m else None


__all__ = ["sign_location", "jitter", "location_distance", "configure_jitter"]
