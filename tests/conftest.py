"""pytest 公共夹具：一个会记账的假学习通服务端。

## 为什么需要它

真实活动不是随时都有（一整天可能一次都没有），但签到的**参数拼装**和
**回执解析**这两段逻辑必须验证。用录制下来的真实报文结构起一个本地服务端，
就能在没有活动的情况下把六种签到全跑一遍。

它不是 mock 掉 `sign()`，而是**用真的 `Session` 发真的 HTTP 请求**，
只是把 URL 指到本地 —— 所以 `net.py` 的限速、重试、302 判定、参数编码全都真跑了。

## 用法

    def test_x(fake_cx):
        fake_cx.set_reply("success")
        result = sign(session, activity, opts)
        assert fake_cx.called("pptSign/stuSignajax")
        assert fake_cx.last_params()["activeId"] == "123"
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeChaoxing/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
        pass

    # ------------------------------------------------------------- 分发
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        body = b""
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""

        params: dict[str, Any] = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if body:
            params.update({k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()})

        state = self.server.state  # type: ignore[attr-defined]
        state["requests"].append(
            {"method": method, "path": parsed.path, "params": params, "headers": dict(self.headers)}
        )

        route = parsed.path
        # 允许测试覆盖任意路由的回执
        override = state["replies"].get(route)
        if override is not None:
            self._send(*override)
            return

        if route.endswith("/newsign/preSign"):
            self._send(200, "<html><body>preSign ok</body></html>")
        elif route.endswith("/pptSign/analysis"):
            code = state["code"]
            self._send(
                200,
                "$.ajax({type:'get',url:'/pptSign/analysis2?DB_STRATEGY=RANDOM&code='+'"
                + code
                + "',success:function(res){}});",
            )
        elif route.endswith("/pptSign/analysis2"):
            self._send(200, "success")
        elif route.endswith("/pptSign/stuSignajax"):
            self._send(200, state["sign_reply"])
        elif route.endswith("/getPPTActiveInfo"):
            self._send(
                200,
                json.dumps(
                    {"result": 1, "data": state["active_info"], "errorMsg": None},
                    ensure_ascii=False,
                ),
            )
        elif route.endswith("/student/activelist"):
            self._send(200, json.dumps(state["active_list"], ensure_ascii=False))
        elif route.endswith("/checkSignCode"):
            self._send(200, state["check_code_reply"])
        else:
            self._send(404, "not found")

    def _send(self, status: int, text: str, headers: dict[str, str] | None = None) -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)


class FakeChaoxing:
    """可编程的假服务端。"""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "requests": [],
            "replies": {},
            "code": "a739c0d230f97395c474edc5ee55762e",
            "sign_reply": "success",
            "check_code_reply": "success",
            "active_info": {"otherId": 0, "ifphoto": 0, "activeSort": 0, "nameOne": "签到"},
            "active_list": {"result": 1, "data": {"activeList": []}},
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.state = self.state  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # ---------------------------------------------------------- 生命周期
    def start(self) -> None:
        # poll_interval 调小，否则每次 shutdown() 都要等满 0.5s
        self._thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def base(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    # ------------------------------------------------------------- 编程
    def set_reply(self, text: str) -> None:
        self.state["sign_reply"] = text

    def set_active_info(self, **fields: Any) -> None:
        self.state["active_info"].update(fields)

    def set_active_list(self, activities: list[dict]) -> None:
        self.state["active_list"] = {"result": 1, "data": {"activeList": activities}}

    def override(self, path_suffix: str, status: int, text: str, headers: dict | None = None) -> None:
        """接管某个路由（用于模拟 302 未登录等）。"""
        for existing in list(self.state["replies"]):
            if existing.endswith(path_suffix):
                del self.state["replies"][existing]
        self.state["replies"][f"/{path_suffix.lstrip('/')}"] = (status, text, headers or {})

    def reset(self) -> None:
        self.state["requests"].clear()
        self.state["replies"].clear()
        self.state["sign_reply"] = "success"
        self.state["code"] = "a739c0d230f97395c474edc5ee55762e"
        self.state["check_code_reply"] = "success"
        self.state["active_info"] = {"otherId": 0, "ifphoto": 0, "activeSort": 0, "nameOne": "签到"}

    # ------------------------------------------------------------- 查询
    def called(self, path_suffix: str) -> bool:
        return any(r["path"].endswith(path_suffix) for r in self.state["requests"])

    def calls(self, path_suffix: str) -> list[dict]:
        return [r for r in self.state["requests"] if r["path"].endswith(path_suffix)]

    def last_params(self, path_suffix: str = "pptSign/stuSignajax") -> dict[str, Any]:
        rows = self.calls(path_suffix)
        assert rows, f"没有调用 {path_suffix}"
        return rows[-1]["params"]

    def paths(self) -> list[str]:
        return [r["path"] for r in self.state["requests"]]


@pytest.fixture()
def fake_cx(monkeypatch):
    """启动假服务端，并把 endpoints 里的域名全部指向它。"""
    from cxsign import endpoints, presign

    # 上报链里那 500ms 是给真实 H5 行为对齐用的，测试没必要等
    monkeypatch.setattr(presign, "SUBMIT_DELAY", 0.0)

    server = FakeChaoxing()
    server.start()
    base = server.base

    attrs = [
        "LOGIN", "ACCOUNT_MANAGE", "COURSE_LIST", "COURSE_LIST_ALT",
        "ACTIVE_LIST", "ACTIVE_INFO", "PRE_SIGN", "ANALYSIS", "ANALYSIS2",
        "STU_SIGN_AJAX", "CHECK_SIGN_CODE", "CHAT_PRE_SIGN", "CHAT_SIGN_AJAX",
        "PAN_HOME", "PAN_LIST", "PAN_TOKEN", "PAN_UPLOAD",
    ]
    for attr in attrs:
        if hasattr(endpoints, attr):
            monkeypatch.setattr(endpoints, attr, f"{base}/{attr.lower()}")

    # 路由需要能按真实后缀匹配，所以保留可读后缀
    monkeypatch.setattr(endpoints, "PRE_SIGN", f"{base}/newsign/preSign")
    monkeypatch.setattr(endpoints, "ANALYSIS", f"{base}/pptSign/analysis")
    monkeypatch.setattr(endpoints, "ANALYSIS2", f"{base}/pptSign/analysis2")
    monkeypatch.setattr(endpoints, "STU_SIGN_AJAX", f"{base}/pptSign/stuSignajax")
    monkeypatch.setattr(endpoints, "ACTIVE_INFO", f"{base}/v2/apis/active/getPPTActiveInfo")
    monkeypatch.setattr(endpoints, "ACTIVE_LIST", f"{base}/v2/apis/active/student/activelist")

    yield server
    server.stop()
