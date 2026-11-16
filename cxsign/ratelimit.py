"""全局令牌桶 —— 跨账号共享的总出口速率。

单个 ``Session`` 有自己的 ``min_interval``（保护同一账号不被判定为脚本），
但多账号并发时还需要一个**总闸**：否则 20 个账号 × 3 线程同时打过去，
出口 IP 段照样会被整段限流。

两层限速的职责：

    Session._pace()      每个账号自己的节奏（默认 0.4s/次）
    GlobalBucket        整个进程的总吞吐（默认 8 次/秒）
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """经典令牌桶。rate = 每秒补充的令牌数，burst = 桶容量。"""

    def __init__(self, rate: float = 8.0, burst: int = 0) -> None:
        self.rate = max(0.1, float(rate))
        self.capacity = max(1, int(burst) or int(self.rate))
        self._tokens = float(self.capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last = now

    def acquire(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """取令牌。timeout=None 表示无限等待，返回 False 表示超时。"""
        need = max(1, int(tokens))
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= need:
                    self._tokens -= need
                    return True
                missing = need - self._tokens
                wait = missing / self.rate

            if deadline is not None and time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))

    # 便于观察
    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<TokenBucket rate={self.rate}/s burst={self.capacity} tokens={self.available:.2f}>"


class NullBucket:
    """不限制。测试和单账号场景用。"""

    rate = float("inf")

    def acquire(self, tokens: int = 1, timeout: float | None = None) -> bool:
        return True

    @property
    def available(self) -> float:
        return float("inf")
