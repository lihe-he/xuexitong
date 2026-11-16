"""监听模式：轮询 → 发现进行中签到 → 自动签 → 推送。

为什么不走 WebSocket：学习通的签到推送不走公开协议，``im.chaoxing.com``
那套只有 App 内部用，逆向成本高且随时变更。实测 ``activelist`` 轮询 15~25 秒
一次，从老师开签到到自动签上通常 20 秒内，足够。

去重靠两把锁：
1. 内存 set（本轮）
2. SQLite sign_logs（跨重启）
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from . import notify
from .activity import Activity, describe
from .config import Settings
from .engine import Engine
from .net import AuthExpired, CxError
from .signer import SignOptions

log = logging.getLogger("cxsign.monitor")


@dataclass(slots=True)
class MonitorState:
    running: bool = False
    started_at: float = 0.0
    rounds: int = 0
    last_scan_at: float = 0.0
    last_error: str = ""
    current_text: str = "未启动"
    handled: dict[str, float] = field(default_factory=dict)


class Monitor:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        *,
        poll_interval: int | None = None,
        auto_sign: bool = True,
        on_event: Any = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.poll_interval = poll_interval or settings.poll_interval
        self.auto_sign = auto_sign
        self.on_event = on_event
        self.state = MonitorState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # 一轮里第几个待签的账号，用来递增错峰间隔
        self._spread_index = 0

    # ------------------------------------------------------------- control
    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self.state.running = True
            self.state.started_at = time.time()
            self.state.current_text = f"监听中，间隔 {self.poll_interval}s"
            self._thread = threading.Thread(target=self._loop, name="cxsign-monitor", daemon=True)
            self._thread.start()
        log.info("监听已启动，间隔 %ss", self.poll_interval)
        return True

    def stop(self, wait: bool = True) -> bool:
        with self._lock:
            if not self._thread:
                self.state.running = False
                return False
            self._stop.set()
            thread = self._thread
        if wait:
            thread.join(timeout=5)
        with self._lock:
            self.state.running = False
            self.state.current_text = "已停止"
            self._thread = None
        log.info("监听已停止")
        return True

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---------------------------------------------------------------- loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 —— 单轮异常不能杀死监听
                self.state.last_error = str(exc)
                log.exception("监听轮次异常：%s", exc)
            self._stop.wait(self.poll_interval)

    def tick(self) -> list[Activity]:
        """跑一轮。返回本轮发现的签到活动。"""
        self.state.rounds += 1
        self.state.last_scan_at = time.time()
        self._spread_index = 0
        found: list[Activity] = []

        for account in self.engine.store.list_accounts(only_enabled=True):
            try:
                activities = self.engine.scan(account.id, refresh_courses=self.state.rounds % 20 == 0)
            except AuthExpired as exc:
                self._event("auth", f"账号 {account.username} 登录态失效", str(exc))
                continue
            except CxError as exc:
                log.warning("账号 %s 扫描失败：%s", account.username, exc)
                continue

            if not activities:
                log.debug("第 %d 轮：%s 无进行中签到", self.state.rounds, account.username)
                continue

            for act in activities:
                key = f"{account.id}:{act.active_id}"
                if key in self.state.handled:
                    continue
                if self.engine.store.already_signed(account.id, act.active_id):
                    self.state.handled[key] = time.time()
                    continue

                found.append(act)
                self.state.current_text = f"发现 {account.username} → {describe(act.kind)}"
                self._event(
                    "discover",
                    f"发现签到｜{account.username}",
                    f"{act.course}\n{act.name}\n类型：{describe(act.kind)}",
                )

                if not self.auto_sign:
                    self.state.handled[key] = time.time()
                    continue

                if act.needs_input:
                    self.state.handled[key] = time.time()
                    # 二维码活动：把目标写进缓存，抢签器拿到 enc 后可以立刻提交，
                    # 不用再花 10 秒全量扫描一遍课程
                    if act.needs_input == "enc":
                        self.engine.store.save_qr_target(
                            account.id, act.active_id, act.course.course_id, act.course.class_id
                        )
                    self._event(
                        "need-input",
                        f"需要人工输入｜{account.username}",
                        f"{act.name} 是{describe(act.kind)}，缺少 {act.needs_input}，请在面板提交",
                    )
                    continue

                # 人类反应时间：发现签到后不会 0 毫秒就提交。
                # 多账号场景再叠加一个按序递增的间隔，避免所有人在同一秒落库。
                delay = random.uniform(
                    self.settings.sign_delay_min, max(self.settings.sign_delay_min, self.settings.sign_delay_max)
                )
                delay += self._spread_index * self.settings.multi_account_spread
                self._spread_index += 1
                if delay > 0:
                    log.debug("等待 %.1fs 后提交（模拟反应时间）", delay)
                    if self._stop.wait(delay):
                        return found

                result = self._sign_one(account.id, act)
                if result is not None and not result.ok:
                    # 失败不标记 handled，下轮再试（最多 3 次，靠时间窗兜底）
                    if act.age_seconds > self.settings.activity_ttl:
                        self.state.handled[key] = time.time()
                else:
                    self.state.handled[key] = time.time()

        self.state.last_scan_at = time.time()
        # 每 30 轮（默认约 10 分钟）打一条心跳，方便确认进程还活着
        if self.state.rounds % 30 == 0:
            log.info(
                "心跳：第 %d 轮，已处理 %d 条，最近无异常",
                self.state.rounds,
                len(self.state.handled),
            )
        return found

    def _sign_one(self, account_id: int, act: Activity):
        try:
            delegation = self.engine.store.active_delegation(account_id)
            result = self.engine.sign(
                account_id,
                act,
                SignOptions(),
                delegation_id=int(delegation["id"]) if delegation else 0,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("签到异常：%s", exc)
            self._event("sign-error", f"签到异常｜{act.name}", str(exc))
            return None

        if result.ok:
            self._event(
                "signed",
                f"✅ 签到成功｜{describe(act.kind)}",
                f"{act.course}\n{act.name}\n{result.message}",
            )
        else:
            self._event(
                "sign-failed",
                f"❌ 签到失败｜{describe(act.kind)}",
                f"{act.course}\n{act.name}\n{result.message}",
            )
        return result

    # -------------------------------------------------------------- events
    def _event(self, kind: str, title: str, text: str) -> None:
        log.info("[%s] %s", kind, title)
        if kind != "auth":
            notify.notify(self.settings.notify, title, text)
        if self.on_event is not None:
            try:
                self.on_event({"kind": kind, "title": title, "text": text, "ts": time.time()})
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "rounds": self.state.rounds,
            "last_scan_at": self.state.last_scan_at,
            "last_error": self.state.last_error,
            "current": self.state.current_text,
            "handled": len(self.state.handled),
            "interval": self.poll_interval,
            "auto_sign": self.auto_sign,
        }
