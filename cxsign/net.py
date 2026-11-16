"""统一 HTTP 层：Cookie 持久化、限速、重试、登录态识别。

设计要点（踩过的坑）：

* `courselistdata` / `activelist` 在登录态失效时返回 **302 而不是 401**，
  所以必须 ``follow_redirects=False`` 并检查 Location 是否指向 passport2。
* 学习通对高频请求会直接返回 **空 JSON**（``data: null``）而不是错误码，
  这种要当"请求过频"处理，退避重试，不能当"没有签到"。
* Cookie 里 ``_uid`` / ``fid`` / ``_d`` / ``vc3`` 是后续所有接口的凭据，
  必须整份保存，不能只存一个。
"""

from __future__ import annotations

import json
import random
import ssl
import threading
import time
from typing import Any

import httpx

from .config import DEFAULT_UA, Settings

#: 共享的 SSL 上下文。
#:
#: httpx 每次 `Client()` 都会自己 build 一个上下文，在 Windows 上要 **1.0 秒**
#: （加载系统证书库）。20 个账号就是 20 秒纯启动开销。
#: 预建一份复用后降到 **0.03 秒**。20 个账号 = 省 20 秒。
_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def shared_ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    with _SSL_LOCK:
        if _SSL_CONTEXT is None:
            _SSL_CONTEXT = httpx.create_ssl_context()
        return _SSL_CONTEXT


class CxError(Exception):
    """本项目所有业务异常的基类。"""


class AuthExpired(CxError):
    """登录态失效，需要重新登录。"""


class TooFrequent(CxError):
    """被限流：接口返回空 data。"""


class ApiError(CxError):
    """接口返回了非预期内容。"""


class Session:
    """一个账号 = 一个 Session = 一份 Cookie。线程内使用，跨线程请加锁。"""

    def __init__(
        self,
        *,
        ua: str = DEFAULT_UA,
        timeout: float = 15.0,
        proxy: str | None = None,
        min_interval: float = 0.4,
        retries: int = 3,
        cookies: dict[str, str] | None = None,
        bucket: Any = None,
    ) -> None:
        self.ua = ua
        self.min_interval = min_interval
        self.retries = retries
        self.bucket = bucket
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            proxy=proxy or None,
            verify=shared_ssl_context(),
            headers={
                "User-Agent": ua,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "*/*",
            },
        )
        if cookies:
            self.client.cookies.update(cookies)

    @classmethod
    def from_settings(cls, settings: Settings, **kw: Any) -> Session:
        return cls(
            ua=settings.ua,
            timeout=settings.timeout,
            proxy=settings.proxy,
            min_interval=settings.min_interval,
            retries=settings.retries,
            **kw,
        )

    @classmethod
    def from_identity(
        cls, settings: Settings, identity: Any = None, **kw: Any
    ) -> Session:
        """按账号的设备人格建会话：独立 UA + 独立出口 IP。

        未提供 identity 时退回全局配置（单账号场景够用）。
        """
        if identity is None:
            return cls.from_settings(settings, **kw)
        return cls(
            ua=identity.ua or settings.ua,
            timeout=settings.timeout,
            proxy=identity.proxy or settings.proxy,
            min_interval=settings.min_interval,
            retries=settings.retries,
            **kw,
        )
    # ------------------------------------------------------------ 生命周期
    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ Cookie
    @property
    def cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self.client.cookies.jar}

    def load_cookies(self, cookies: dict[str, str]) -> None:
        self.client.cookies.clear()
        self.client.cookies.update(cookies)

    @property
    def uid(self) -> str:
        c = self.cookies
        uid = c.get("_uid") or c.get("UID")
        if not uid:
            raise AuthExpired("Cookie 中没有 _uid，尚未登录或已失效")
        return uid

    @property
    def fid(self) -> str:
        return self.cookies.get("fid", "0") or "0"

    # ------------------------------------------------------------ 请求
    def _pace(self) -> None:
        # 先过全局总闸（跨账号共享），再过本账号自己的节奏
        if self.bucket is not None:
            self.bucket.acquire()
        if self.min_interval <= 0:
            return
        with self._lock:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.15))
            self._last_call = time.monotonic()

    def request(
        self, method: str, url: str, *, retries: int | None = None, **kw: Any
    ) -> httpx.Response:
        headers = dict(kw.get("headers") or {})
        headers.setdefault("Referer", "https://mobilelearn.chaoxing.com/")
        kw["headers"] = headers
        attempts = self.retries if retries is None else max(1, int(retries))
        last_exc: Exception | None = None
        for attempt in range(attempts):
            self._pace()
            try:
                resp = self.client.request(method, url, **kw)
            except httpx.HTTPError as exc:  # 网络层抖动
                last_exc = exc
                time.sleep(0.6 * (attempt + 1))
                continue

            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location", "")
                raise_or_return = self._logged_out_location(loc)
                if raise_or_return:
                    raise AuthExpired(f"被重定向到登录页：{loc[:120]}")
                # 其它跳转按最终内容处理不了，直接返回
                return resp

            if resp.status_code >= 500:
                last_exc = ApiError(f"HTTP {resp.status_code}: {url}")
                time.sleep(0.8 * (attempt + 1))
                continue

            return resp

        raise ApiError(f"请求失败（已重试 {attempts} 次）：{url}") from last_exc

    @staticmethod
    def _logged_out_location(location: str) -> bool:
        """识别「未登录」的跳转目标。

        学习通有三种，实测（2026-11）都出现过：

        * ``https://passport2.chaoxing.com/mlogin?...``      —— activelist / webim
        * ``/widget/mobileError?errormsg=请登录...``         —— preSign（**容易被漏掉**）
        * ``http://passport2.chaoxing.com/wlogin?...``       —— 旧接口
        """
        from urllib.parse import unquote

        low = location.lower()
        if "passport2" in low or "/mlogin" in low or "/wlogin" in low:
            return True
        if "mobileerror" in low:
            return True
        return "登录" in unquote(location)

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)

    def get_json(self, url: str, **kw: Any) -> Any:
        resp = self.get(url, **kw)
        text = resp.text
        if not text.strip():
            raise TooFrequent("接口返回空响应")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(f"非 JSON 响应：{text[:200]}") from exc
