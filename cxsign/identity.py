"""身份隔离层 —— 一个账号一份"设备人格"。

## 为什么需要

学习通服务端能看到的关联特征至少有这些：

| 特征 | 来源 | 单点托管多个账号的后果 |
|---|---|---|
| 出口 IP | TCP 源地址 | 同 IP 下 N 个账号在同一分钟签到，最强关联信号 |
| `User-Agent` | 请求头 | 全班用同一个小米 UA，不自然 |
| `deviceCode` | 签到接口参数 | 同一个设备码签十几个人的到，等于自报代签 |
| `Cookie` 里的 `_d` / `vc3` | 登录时下发 | 由服务端生成，改不了，但**每个账号本来就不同** |
| 提交时间戳 | 服务器收包时刻 | 秒级聚集（相差 < 2 秒）在真人里几乎不可能 |
| 坐标 | 位置签到参数 | 所有人同一个经纬度，`getAttendInfo` 里一目了然 |

本模块负责其中**可控**的四项：出口 IP、UA、deviceCode、时间抖动。
`_d` / `vc3` 由服务端下发，动不了，也不用动 —— 它们天然按账号隔离。

## 派生原则

所有身份字段都由 `账号 ID + 用户名` 稳定派生，**同一账号每次运行必须拿到同一套身份**。
随机化的身份反而更可疑：一个学号一天换三个设备，比一直用同一台更异常。

必须变的是**行为**（时间抖动、坐标抖动），不是身份。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: 真实在售/在用的 Android 机型 UA，按账号稳定分配
UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Linux; Android 13; SM-S9110 Build/TP1A.220624.014; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/129.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240305.019.A1; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi K50 Build/SKQ1.211006.001; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; OPPO Find X6 Build/TP1A.220905.001; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/127.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; V2227A Build/TP1A.220624.014; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; 23127PN0CC Build/UKQ1.231003.002; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; HarmonyOS; ALN-AL00 Build/HUAWEIALN-AL00; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; M2102K1AC Build/TKQ1.220829.002; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7a Build/AP1A.240505.004; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/129.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; 22081212C Build/TKQ1.220905.001; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Redmi Note 11T Pro Build/RKQ1.211001.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-F9460 Build/UP1A.231005.007; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/129.0.0.0 Mobile Safari/537.36",
)


@dataclass(slots=True, frozen=True)
class Identity:
    """一份账号专属的设备人格。"""

    device_code: str
    ua: str
    proxy: str | None = None

    def to_row(self) -> dict[str, str]:
        return {
            "device_code": self.device_code,
            "ua": self.ua,
            "proxy": self.proxy or "",
        }


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _index(seed: str, modulo: int) -> int:
    return int(_digest(seed)[:8], 16) % modulo


def make_device_code(seed: str) -> str:
    """稳定派生 deviceCode（32 位 hex）。

    真实客户端下发的是形如 ``a1b2c3d4e5f6...`` 的 32 位串，长度对齐即可。
    """
    return _digest(f"device::{seed}")[:32]


def pick_ua(seed: str) -> str:
    return UA_POOL[_index(f"ua::{seed}", len(UA_POOL))]


def pick_proxy(
    seed: str,
    proxies: list[str] | tuple[str, ...] | None,
    *,
    index_hint: int = -1,
) -> str | None:
    """按账号稳定分配出口 IP。

    给了 ``index_hint``（通常是 account_id）就走取模，能保证池子够大时**不重复**；
    否则退化为哈希。池子大小小于账号数时必然共享，这是物理限制 —— 要么加代理，
    要么接受同出口，靠时间抖动降低关联强度。
    """
    if not proxies:
        return None
    clean = [p for p in proxies if p and p.strip()]
    if not clean:
        return None
    if index_hint >= 0:
        return clean[index_hint % len(clean)]
    return clean[_index(f"proxy::{seed}", len(clean))]


def build(
    account_id: int,
    username: str,
    *,
    proxy_pool: list[str] | tuple[str, ...] | None = None,
    device_code: str = "",
    ua: str = "",
    proxy: str = "",
) -> Identity:
    """优先用数据库里已保存的字段，缺失才派生。

    这一点很重要：身份一旦确定不能漂移，否则"同一学号换了设备"本身就是异常信号。
    """
    seed = f"{account_id}:{username}"
    return Identity(
        device_code=device_code or make_device_code(seed),
        ua=ua or pick_ua(seed),
        proxy=proxy or pick_proxy(seed, proxy_pool, index_hint=account_id),
    )
