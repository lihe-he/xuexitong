"""FastAPI 应用：把 Engine / Monitor 暴露成 HTTP 接口，外加一个单页 Web UI。

跑起来：

    python -m cxsign.server --host 0.0.0.0 --port 8000

设计取舍：所有业务都是**同步阻塞**的（httpx + 登录态），所以路由统一写成
``def`` 而不是 ``async def``，交给 Starlette 的线程池，不阻塞事件循环。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..activity import describe
from ..config import Settings
from ..engine import Engine
from ..monitor import Monitor
from ..net import AuthExpired, CxError
from ..runtime import Runtime
from ..runtime import build as build_runtime
from ..signer import SignOptions
from ..signer.qrcode import extract_enc
from ..store import Store

log = logging.getLogger("cxsign.server")
STATIC_DIR = Path(__file__).parent / "static"


# ------------------------------------------------------------------ payloads
class LoginPayload(BaseModel):
    username: str = Field(..., description="手机号")
    password: str = Field(..., description="密码")


class ImportPayload(BaseModel):
    """Cookie 托管（代签 B 档）。"""

    username: str = Field(..., description="对方手机号")
    cookies: str = Field(..., description="Cookie 串 / JSON，至少含 _uid 与 fid")
    operator: str = Field("", description="代为托管的人/标识")
    note: str = Field("", description="备注：授权来源、有效期等")


class EnablePayload(BaseModel):
    enabled: bool = True


class QrPayload(BaseModel):
    enc: str = Field("", description="已知的 enc")
    qr_text: str = Field("", description="二维码原文（URL / 裸串），自动解析")


class SignPayload(BaseModel):
    account_id: int
    active_id: str
    sign_code: str = ""
    enc: str = ""
    qr_text: str = Field("", description="二维码扫描原始文本，自动解析 enc")
    lat: str = ""
    lon: str = ""
    address: str = ""
    object_id: str = ""
    photo_path: str = ""


class MonitorPayload(BaseModel):
    interval: int | None = None
    auto_sign: bool = True


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or build_runtime(settings or Settings.load())
    settings = rt.settings
    store: Store = rt.store
    engine: Engine = rt.engine
    monitor_holder: dict[str, Monitor] = {}

    def get_monitor() -> Monitor:
        m = monitor_holder.get("m")
        if m is None:
            m = Monitor(settings, engine)
            monitor_holder["m"] = m
        return m

    app = FastAPI(title="cxsign", version="0.2.1", description="超星学习通自动签到")
    app.state.runtime = rt
    app.state.settings = settings
    app.state.store = store
    app.state.engine = engine

    @app.on_event("shutdown")
    def _shutdown() -> None:
        m = monitor_holder.get("m")
        if m is not None:
            m.stop(wait=False)
        rt.close()

    # ------------------------------------------------------------- meta
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        from .. import qrdecode

        return {
            "ok": True,
            "version": app.version,
            "data_dir": str(settings.data_dir),
            "secret_source": rt.secret.source,
            "qr_decode": qrdecode.available(),
            "global_rate": settings.global_rate,
            "isolate_identity": settings.isolate_identity,
            "proxy_pool": len(settings.proxy_pool),
        }

    # --------------------------------------------------------- accounts
    @app.get("/api/accounts")
    def list_accounts() -> list[dict[str, Any]]:
        out = []
        for a in store.list_accounts():
            delegation = store.active_delegation(a.id)
            out.append(
                {
                    "id": a.id,
                    "username": a.username,
                    "real_name": a.real_name,
                    "enabled": a.enabled,
                    "has_password": bool(a.password),
                    "password_mask": "已加密" if a.password else "",
                    "cookie_ok": bool(a.cookies.get("_uid") or a.cookies.get("UID")),
                    "mode": "password" if a.password else ("cookie" if a.cookies else "none"),
                    "owner": a.owner,
                    "remark": a.remark,
                    "device_code": a.device_code[:8],
                    "proxy": a.proxy or "直连",
                    "delegation": (
                        {"id": delegation["id"], "operator": delegation["operator"]}
                        if delegation
                        else None
                    ),
                    "cooling_down": int(engine.cooling_down(a.id)),
                    "updated_at": a.updated_at,
                }
            )
        return out

    @app.post("/api/accounts/login")
    def login(payload: LoginPayload) -> dict[str, Any]:
        try:
            return engine.login_and_save(payload.username, payload.password)
        except CxError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/accounts/import")
    def import_cookies(payload: ImportPayload) -> dict[str, Any]:
        """Cookie 托管：对方在自己手机登录后导出 Cookie，不涉及密码。"""
        try:
            return engine.import_cookies(
                payload.username, payload.cookies, operator=payload.operator, note=payload.note
            )
        except (CxError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/enable")
    def enable(account_id: int, payload: EnablePayload) -> dict[str, Any]:
        if store.get_account(account_id) is None:
            raise HTTPException(404, "账号不存在")
        store.set_enabled(account_id, payload.enabled)
        return {"ok": True}

    @app.delete("/api/accounts/{account_id}")
    def remove_account(account_id: int) -> dict[str, Any]:
        if store.get_account(account_id) is None:
            raise HTTPException(404, "账号不存在")
        store.set_enabled(account_id, False)
        engine.drop_session(account_id)
        return {"ok": True, "note": "已禁用，未物理删除历史日志"}

    # ------------------------------------------------------ delegations
    @app.get("/api/accounts/{account_id}/delegation")
    def get_delegation(account_id: int) -> dict[str, Any] | None:
        return store.active_delegation(account_id)

    @app.post("/api/delegations/{delegation_id}/revoke")
    def revoke_delegation(delegation_id: int) -> dict[str, Any]:
        store.revoke_delegation(delegation_id)
        return {"ok": True}

    # ---------------------------------------------------------- courses
    @app.get("/api/accounts/{account_id}/courses")
    def courses(account_id: int, sync: bool = False) -> list[dict[str, str]]:
        try:
            if sync:
                return engine.sync_courses(account_id)
        except AuthExpired as exc:
            raise HTTPException(401, str(exc)) from exc
        except CxError as exc:
            raise HTTPException(400, str(exc)) from exc
        return engine.store.list_courses(account_id)

    # ------------------------------------------------------- activities
    @app.get("/api/accounts/{account_id}/activities")
    def activities(account_id: int, sync: bool = False) -> list[dict[str, Any]]:
        try:
            found = engine.scan(account_id, refresh_courses=sync, use_backoff=False)
        except AuthExpired as exc:
            raise HTTPException(401, str(exc)) from exc
        except CxError as exc:
            raise HTTPException(400, str(exc)) from exc
        return [
            {
                "active_id": a.active_id,
                "name": a.name,
                "course": str(a.course),
                "course_id": a.course.course_id,
                "class_id": a.course.class_id,
                "kind": a.kind.value,
                "kind_text": describe(a.kind),
                "needs_input": a.needs_input,
                "start_time": a.start_time,
                "age_seconds": int(a.age_seconds),
            }
            for a in found
        ]

    # ------------------------------------------------------- qr decode
    @app.post("/api/qr/decode")
    def qr_decode(payload: QrPayload) -> dict[str, Any]:

        enc = payload.enc or extract_enc(payload.qr_text)
        if enc:
            return {"ok": True, "enc": enc, "source": "text"}
        raise HTTPException(400, "没有可解析的内容")

    @app.post("/api/qr/decode-image")
    async def qr_decode_image(request: Request) -> dict[str, Any]:
        """接收原始图片字节（Content-Type: image/*），返回 enc。

        用 Request.body() 而不是 UploadFile，避免引入 python-multipart 依赖。
        """
        from .. import qrdecode

        body = await request.body()
        if not body:
            raise HTTPException(400, "请求体为空，请直接 POST 图片二进制")
        if len(body) > 8 * 1024 * 1024:
            raise HTTPException(413, "图片超过 8MB")
        try:
            enc = qrdecode.decode_enc(body)
        except qrdecode.QrDecodeError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "enc": enc, "source": "image"}

    # -------------------------------------------------------------- sign
    @app.post("/api/sign")
    def do_sign(payload: SignPayload) -> dict[str, Any]:
        if store.get_account(payload.account_id) is None:
            raise HTTPException(404, "账号不存在")

        activities_found = []
        try:
            activities_found = engine.scan(payload.account_id, use_backoff=False)
        except CxError as exc:
            log.warning("签名前扫描失败：%s", exc)

        target = next((a for a in activities_found if a.active_id == payload.active_id), None)
        if target is None:
            raise HTTPException(404, "该活动不在当前进行中列表里（可能已结束）")

        enc = payload.enc or extract_enc(payload.qr_text)
        delegation = store.active_delegation(payload.account_id)
        opts = SignOptions(
            sign_code=payload.sign_code,
            enc=enc,
            lat=payload.lat or settings.default_lat,
            lon=payload.lon or settings.default_lon,
            address=payload.address or settings.default_address,
            object_id=payload.object_id,
            extra={"photo_path": payload.photo_path} if payload.photo_path else {},
        )
        try:
            result = engine.sign(
                payload.account_id,
                target,
                opts,
                delegation_id=int(delegation["id"]) if delegation else 0,
            )
        except AuthExpired as exc:
            raise HTTPException(401, str(exc)) from exc
        except CxError as exc:
            raise HTTPException(400, str(exc)) from exc

        return {
            "ok": result.ok,
            "message": result.message,
            "kind": result.kind.value,
            "raw": result.raw,
        }

    # --------------------------------------------------------------- logs
    @app.get("/api/logs")
    def logs(limit: int = 100, operator: bool = False) -> list[dict[str, Any]]:
        return store.logs_with_operator(limit) if operator else store.recent_logs(limit)

    # ------------------------------------------------------------ monitor
    @app.get("/api/monitor")
    def monitor_status() -> dict[str, Any]:
        return get_monitor().status()

    @app.post("/api/monitor/start")
    def monitor_start(payload: MonitorPayload | None = None) -> dict[str, Any]:
        m = get_monitor()
        if payload and payload.interval:
            m.poll_interval = int(payload.interval)
        if payload is not None:
            m.auto_sign = payload.auto_sign
        started = m.start()
        return {"ok": True, "started": started, **m.status()}

    @app.post("/api/monitor/stop")
    def monitor_stop() -> dict[str, Any]:
        get_monitor().stop()
        return {"ok": True}

    # --------------------------------------------------------------- ui
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> Any:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            return JSONResponse({"detail": "静态页面缺失"}, status_code=500)
        return FileResponse(page)

    return app


app = create_app()
