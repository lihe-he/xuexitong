"""运行时装配：把 settings / 密钥 / 存储 / 引擎 / 令牌桶拼起来。

CLI 和 Web 服务都需要这套装配，抽出来避免两边配置漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .engine import Engine
from .ratelimit import NullBucket, TokenBucket
from .security import SecretBox
from .store import Store


@dataclass(slots=True)
class Runtime:
    settings: Settings
    secret: SecretBox
    store: Store
    engine: Engine
    bucket: Any

    def close(self) -> None:
        try:
            self.engine.close()
        finally:
            self.store.close()


def build(settings: Settings | None = None) -> Runtime:
    settings = settings or Settings.load()
    secret = SecretBox.load(settings.data_dir)
    store = Store(settings.database, secret=secret)
    bucket = (
        TokenBucket(rate=settings.global_rate, burst=settings.global_burst)
        if settings.global_rate > 0
        else NullBucket()
    )
    engine = Engine(settings, store, bucket=bucket)
    return Runtime(settings=settings, secret=secret, store=store, engine=engine, bucket=bucket)
