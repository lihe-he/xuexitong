"""业务引擎：把 store / net / auth / activity / signer 串成可调用的动作。

对外动作：

    engine.login_and_save(username, password)      # 登录 + 固化身份
    engine.import_cookies(username, raw, operator) # Cookie 托管（不碰密码）
    engine.sync_courses(account_id)                # 刷新课程缓存
    engine.scan(account_id)                        # 并发扫所有课程的进行中签到
    engine.sign(account_id, activity, opts)        # 签一个

三条横切关注点都在这层收口：
* 登录态：每次动作前校验，有密码就自动续命
* 限流退避：被 `TooFrequent` 打过就按指数退避，别每轮死磕
* 审计：签到日志带上 delegation_id，能回答"谁授权签的"
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import activity as activity_mod
from . import auth
from . import identity as identity_mod
from .config import Settings
from .course import Course, parse_cookies
from .net import AuthExpired, CxError, Session, TooFrequent
from .signer import SignOptions, SignResult
from .signer import sign as do_sign
from .store import AccountRow, Store

log = logging.getLogger("cxsign.engine")


class Engine:
    def __init__(self, settings: Settings, store: Store, bucket: Any = None) -> None:
        self.settings = settings
        self.store = store
        self.bucket = bucket
        self._sessions: dict[int, Session] = {}
        self._lock = threading.RLock()
        # account_id -> 允许再次请求的时间戳
        self._retry_after: dict[int, float] = {}
        # account_id -> 连续退避次数（用于指数增长）
        self._backoff_count: dict[int, int] = {}

    # ------------------------------------------------------------ backoff
    def cooling_down(self, account_id: int) -> float:
        """返回还要等多少秒；0 表示现在可以打。"""
        until = self._retry_after.get(account_id, 0.0)
        return max(0.0, until - time.monotonic())

    def note_throttled(self, account_id: int) -> float:
        """被限流了：指数退避。返回本次设定的等待秒数。"""
        n = self._backoff_count.get(account_id, 0)
        delay = min(self.settings.backoff_max, self.settings.backoff_base * (2**n))
        self._backoff_count[account_id] = n + 1
        self._retry_after[account_id] = time.monotonic() + delay
        log.warning("账号 %s 被限流，退避 %.0fs（第 %d 次）", account_id, delay, n + 1)
        return delay

    def note_ok(self, account_id: int) -> None:
        self._backoff_count.pop(account_id, None)
        self._retry_after.pop(account_id, None)

    def clear_backoff(self) -> None:
        with self._lock:
            self._retry_after.clear()
            self._backoff_count.clear()

    # ------------------------------------------------------------- identity
    def identity_of(self, account: AccountRow) -> identity_mod.Identity | None:
        """取账号的设备人格。身份必须稳定，所以首次生成后立刻落库。"""
        if not self.settings.isolate_identity:
            return None

        ident = identity_mod.build(
            account.id,
            account.username,
            proxy_pool=self.settings.proxy_pool,
            device_code=account.device_code,
            ua=account.ua,
            proxy=account.proxy,
        )
        if not (account.device_code and account.ua):
            self.store.save_identity(account.id, ident)
            account.device_code = ident.device_code
            account.ua = ident.ua
            account.proxy = ident.proxy or ""
            log.info(
                "账号 %s 分配身份：device=%s… ua=%s… proxy=%s",
                account.username,
                ident.device_code[:8],
                ident.ua[13:40],
                ident.proxy or "直连",
            )
        return ident

    # ------------------------------------------------------------- session
    def session_of(self, account: AccountRow) -> Session:
        with self._lock:
            sess = self._sessions.get(account.id)
            if sess is None:
                sess = Session.from_identity(
                    self.settings,
                    self.identity_of(account),
                    cookies=account.cookies or None,
                    bucket=self.bucket,
                )
                self._sessions[account.id] = sess
            return sess

    def drop_session(self, account_id: int) -> None:
        with self._lock:
            sess = self._sessions.pop(account_id, None)
        if sess is not None:
            sess.close()

    def ensure_session(self, account: AccountRow) -> Session:
        """拿到一个确认可用的 session；失效则用保存的密码重登并回写 Cookie。"""
        sess = self.session_of(account)
        if auth.validate(sess):
            return sess

        log.info("账号 %s 登录态失效，尝试重登", account.username)
        self.drop_session(account.id)
        if not (account.username and account.password):
            raise AuthExpired(
                f"账号 {account.username} 登录态失效且没有保存密码（Cookie 托管模式），"
                "需要重新导入 Cookie"
            )

        sess = self.session_of(account)
        cookies = auth.login(sess, account.username, account.password)
        name = auth.whoami(sess) or account.real_name
        self.store.upsert_account(
            account.username, password=account.password, real_name=name, cookies=cookies
        )
        account.cookies = cookies
        account.real_name = name
        return sess

    # ------------------------------------------------------------- courses
    def sync_courses(self, account_id: int) -> list[dict[str, str]]:
        from .course import list_courses

        account = self._require(account_id)
        sess = self.ensure_session(account)
        try:
            courses = list_courses(sess)
        except TooFrequent:
            self.note_throttled(account_id)
            raise
        payload = [
            {"course_id": c.course_id, "class_id": c.class_id, "name": c.name} for c in courses
        ]
        self.store.replace_courses(account_id, payload)
        if payload:
            self.note_ok(account_id)
        log.info("账号 %s 同步到 %d 门课程", account.username, len(payload))
        return payload

    def cached_courses(self, account_id: int) -> list[Course]:
        return [
            Course(course_id=c["course_id"], class_id=c["class_id"], name=c["name"])
            for c in self.store.list_courses(account_id)
        ]

    # ---------------------------------------------------------------- scan
    def _scan_course(
        self, sess: Session, course: Course
    ) -> tuple[list[activity_mod.Activity], bool]:
        """扫一门课。返回 (活动列表, 是否被限流)。"""
        try:
            items = activity_mod.list_activities(sess, course, fid=sess.fid)
            return items, False
        except TooFrequent:
            return [], True
        except AuthExpired:
            raise
        except CxError as exc:
            log.warning("扫描课程 %s 失败：%s", course, exc)
            return [], False

    def scan(
        self,
        account_id: int,
        *,
        refresh_courses: bool = False,
        use_backoff: bool = True,
    ) -> list[activity_mod.Activity]:
        """扫出该账号下所有「进行中的签到」。

        多门课并发扫（`scan_concurrency`），但共享全局令牌桶，总出口速率可控。
        """
        if use_backoff:
            wait = self.cooling_down(account_id)
            if wait > 0:
                log.debug("账号 %s 仍在退避中，还剩 %.0fs", account_id, wait)
                return []

        account = self._require(account_id)
        sess = self.ensure_session(account)
        courses = self.cached_courses(account_id)
        if refresh_courses or not courses:
            try:
                self.sync_courses(account_id)
            except TooFrequent:
                return []
            courses = self.cached_courses(account_id)
        if not courses:
            return []

        found: list[activity_mod.Activity] = []
        throttled = False
        workers = max(1, min(self.settings.scan_concurrency, len(courses)))

        if workers == 1:
            for course in courses:
                items, too_fast = self._scan_course(sess, course)
                found.extend(items)
                throttled = throttled or too_fast
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cxsign-scan") as pool:
                futures = {pool.submit(self._scan_course, sess, c): c for c in courses}
                for future in as_completed(futures):
                    try:
                        items, too_fast = future.result()
                    except AuthExpired:
                        log.warning("登录态在扫描中失效，跳过剩余课程")
                        continue
                    except Exception as exc:  # noqa: BLE001
                        log.warning("扫描课程 %s 异常：%s", futures[future], exc)
                        continue
                    found.extend(items)
                    throttled = throttled or too_fast

        if throttled:
            self.note_throttled(account_id)
        else:
            self.note_ok(account_id)
        return found

    # ---------------------------------------------------------------- sign
    def sign(
        self,
        account_id: int,
        target: activity_mod.Activity,
        options: SignOptions | None = None,
        *,
        skip_presign: bool = False,
        delegation_id: int = 0,
    ) -> SignResult:
        account = self._require(account_id)
        sess = self.ensure_session(account)
        opts = options or SignOptions()
        opts.name = opts.name or account.real_name or ""
        # 设备码必须和这个账号绑定的那一份一致，否则等于换设备
        opts.device_code = opts.device_code or account.device_code or ""

        # 二维码签到：没显式给 enc 就用缓存池里的（同一张码全班通用）
        if not opts.enc and target.kind is activity_mod.SignKind.QRCODE:
            cached = self.store.get_enc(target.active_id, max_age=self.settings.enc_ttl)
            if cached:
                opts.enc = cached
                log.info("活动 %s 复用缓存的 enc", target.active_id)

        # 拍照签到必须补一次详情，确认 ifphoto
        if target.kind is activity_mod.SignKind.PLAIN:
            try:
                info = activity_mod.get_active_info(sess, target.active_id)
                real_kind = activity_mod.classify(info)
                if real_kind is not activity_mod.SignKind.PLAIN:
                    log.info("活动 %s 实际类型为 %s，已纠正", target.active_id, real_kind)
                    target.kind = real_kind
            except CxError as exc:
                log.debug("取活动详情失败，沿用列表判定：%s", exc)

        try:
            result = do_sign(sess, target, opts, settings=self.settings, skip_presign=skip_presign)
        except AuthExpired:
            log.info("签到过程中登录态失效，重登后重试一次")
            self.drop_session(account_id)
            self.ensure_session(account)
            result = do_sign(
                self.session_of(account), target, opts, settings=self.settings, skip_presign=True
            )

        self.store.add_log(
            account_id,
            target.active_id,
            course_id=target.course.course_id,
            class_id=target.course.class_id,
            kind=target.kind.value,
            ok=result.ok,
            message=result.message,
            delegation_id=delegation_id,
        )
        return result

    # ------------------------------------------------------------- helpers
    def _require(self, account_id: int) -> AccountRow:
        account = self.store.get_account(account_id)
        if account is None:
            raise CxError(f"账号 {account_id} 不存在")
        return account

    def login_and_save(self, username: str, password: str) -> dict[str, Any]:
        """登录并把 Cookie / 姓名落库。"""
        sess = Session.from_settings(self.settings, bucket=self.bucket)
        try:
            cookies = auth.login(sess, username, password)
            name = auth.whoami(sess)
        finally:
            sess.close()
        account_id = self.store.upsert_account(
            username, password=password, real_name=name, cookies=cookies
        )
        # 登录成功即固定设备人格，之后永不变
        account = self.store.get_account(account_id)
        if account is not None:
            self.identity_of(account)
        return {"account_id": account_id, "username": username, "real_name": name}

    def import_cookies(
        self,
        username: str,
        raw: str | dict[str, str],
        *,
        operator: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Cookie 托管（代签 B 档）：不碰对方密码。

        对方在自己手机上登录一次、导出 Cookie 给你，你只存 Cookie。
        改密码即天然撤销，比密码托管干净。
        """
        cookies = parse_cookies(raw)
        missing = [k for k in ("_uid",) if k not in cookies]
        if missing:
            raise CxError(f"Cookie 缺少关键字段：{', '.join(missing)}（至少要 _uid 和 fid）")

        account_id = self.store.upsert_account(username, real_name="", cookies=cookies)
        # 托管模式下清空密码，避免误用旧密码重登
        self.store.upsert_account(username, password="")
        self.drop_session(account_id)

        account = self.store.get_account(account_id)
        if account is not None:
            self.identity_of(account)
            self.store.set_owner(account_id, operator or "self", note)

        delegation_id = 0
        if operator:
            delegation_id = self.store.add_delegation(
                account_id, operator, note or "cookie-import"
            )

        return {
            "account_id": account_id,
            "username": username,
            "cookie_keys": sorted(cookies),
            "delegation_id": delegation_id,
            "mode": "cookie",
        }

    def close(self) -> None:
        with self._lock:
            ids = list(self._sessions)
        for aid in ids:
            self.drop_session(aid)
