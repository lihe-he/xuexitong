from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- UA / 常量

#: 学生端 H5 / WebView 的 UA。mobilelearn 的签到页都是移动端 H5，
#: 桌面 UA 在部分活动上会拿到空 activeList，用移动 UA 最稳。
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/129.0.0.0 Mobile Safari/537.36"
)

#: fanyalogin 的密码加密密钥（AES-128-CBC，key == iv）
AES_KEY = "u2oh6Vu^HWe4_AES"

#: 旧版 fanyalogin 的密码加密密钥（DES-ECB，hex 输出），作兼容兜底
DES_KEY = "u2oh6Vu^HWe40fj"

#: pptSign/stuSignajax 返回的"成功"字面量
SUCCESS_TOKENS = ("success", "success2")


def _env(key: str, default: Any) -> Any:
    v = os.environ.get(key)
    return default if v in (None, "") else v


@dataclass(slots=True)
class Settings:
    """运行时配置。全部可被环境变量覆盖，方便 Docker 部署。"""

    data_dir: Path = field(default_factory=lambda: Path(_env("CXSIGN_DATA", "data")))
    database: Path | None = None          # 默认 <data_dir>/cxsign.db
    ua: str = DEFAULT_UA
    timeout: float = field(default_factory=lambda: float(_env("CXSIGN_TIMEOUT", 15)))
    proxy: str | None = field(default_factory=lambda: _env("CXSIGN_PROXY", None))
    min_interval: float = field(default_factory=lambda: float(_env("CXSIGN_INTERVAL", 0.4)))
    retries: int = field(default_factory=lambda: int(_env("CXSIGN_RETRIES", 3)))

    # 监听
    poll_interval: int = field(default_factory=lambda: int(_env("CXSIGN_POLL", 20)))
    activity_ttl: int = field(default_factory=lambda: int(_env("CXSIGN_ACTIVITY_TTL", 150)))

    # 位置签到默认点位（BD-09，百度坐标系）
    default_lat: str = "-1"
    default_lon: str = "-1"
    default_address: str = ""
    location_jitter_m: float = 8.0        # 每次签到抖动半径（米），避免所有人同一个点

    # ---------------- 身份隔离（一个账号 = 一份设备人格 + 一条出口）
    isolate_identity: bool = True         # 关掉就所有账号共用 settings.ua / settings.proxy
    proxy_pool: list[str] = field(default_factory=list)   # 出口 IP 池，按账号稳定分配

    # ---------------- 行为抖动（模拟人类反应时间）
    sign_delay_min: float = 3.0           # 发现签到后最少等几秒再提交
    sign_delay_max: float = 25.0          # 最多等几秒
    multi_account_spread: float = 4.0     # 多账号签同一个活动时，相邻账号的额外间隔

    # ---------------- 吞吐与退避
    global_rate: float = 8.0              # 全进程总出口速率（次/秒），0 = 不限
    global_burst: int = 16                # 令牌桶容量
    scan_concurrency: int = 3             # 单账号并发扫课程数
    backoff_base: float = 30.0            # 被限流后首次退避秒数
    backoff_max: float = 600.0            # 退避上限

    # ---------------- 二维码
    enc_ttl: int = 120                    # 缓存的 enc 复用窗口（秒），0 = 不限
    qr_watch_dir: str = "data/qr"         # qr_race 监听的截图目录
    qr_poll_interval: float = 0.5         # 截图目录轮询间隔（秒）

    # ---------------- 推送
    notify: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.database is None:
            self.database = self.data_dir / "cxsign.db"
        self.database = Path(self.database)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- 加载
    @classmethod
    def load(cls, path: str | Path | None = None) -> Settings:
        """从 TOML 加载；文件不存在则返回默认值。"""
        if path is None:
            path = Path(_env("CXSIGN_CONFIG", "config.toml"))
        path = Path(path)
        if not path.is_file():
            return cls()
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in raw.items() if k in known and k != "notify"}
        s = cls(**kwargs)
        s.notify = raw.get("notify", {}) or {}
        return s
