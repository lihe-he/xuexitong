"""本地 Cookie 接收器：把浏览器里的学习通 Cookie 安全地交到项目手上。

浏览器里有 HttpOnly 的 ``vc3``，``document.cookie`` 读不到，但 **Network 面板的
请求头里有**。这个接收器提供粘贴框，避免手抄长串。

    python -m cxsign.tools catcher

然后浏览器打开 http://127.0.0.1:8765/ ，按页面提示复制 ``Cookie:`` 整行粘进去。
结果落到 ``data/caught_cookie.txt``。

安全边界：只监听回环地址；收完可用 ``import`` 后自行删除。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..config import Settings

PAGE = """<!doctype html><meta charset="utf-8">
<title>cxsign · 接收 Cookie</title>
<style>
body{font:14px/1.7 system-ui;max-width:820px;margin:32px auto;padding:0 20px;background:#0f1216;color:#e6edf3}
h2{margin-bottom:4px}h3{margin-top:26px;font-size:13px;color:#8b97a6;text-transform:uppercase;letter-spacing:.6px}
code{background:#181d24;padding:2px 6px;border-radius:4px;font-size:13px}
textarea{width:100%;min-height:150px;background:#0d1117;border:1px solid #28303a;color:#e6edf3;border-radius:8px;
padding:10px;font-family:ui-monospace,Consolas,monospace;font-size:12px;resize:vertical}
button{background:#388bfd;border:none;color:#fff;border-radius:6px;padding:9px 20px;cursor:pointer;font:inherit;margin-top:10px}
button:disabled{background:#28303a;color:#8b97a6}
pre{background:#181d24;padding:12px;border-radius:8px;overflow:auto;border-left:3px solid #388bfd;font-size:12px}
.muted{color:#8b97a6;font-size:13px}ol{padding-left:22px}li{margin:4px 0}
</style>
<h2>cxsign · 接收 Cookie</h2>
<p class="muted">本机服务，不外发。</p>
<h3>怎么拿</h3>
<ol class="muted">
<li>F12 → <b>Network</b>，刷新页面</li>
<li>点任意一条发往 <code>chaoxing.com</code> 的请求</li>
<li>右侧 <b>Headers</b> → <b>Request Headers</b> → <code>Cookie:</code> 那一行</li>
<li>复制整行的值，粘到下面</li>
</ol>
<p class="muted">Network 里的请求头包含 <b>HttpOnly</b> 的 <code>vc3</code>，而
<code>document.cookie</code> 读不到它。</p>
<h3>粘贴</h3>
<textarea id="t" placeholder="Cookie: _uid=...; fid=...; _d=...; vc3=...; uf=..."></textarea>
<button id="b" onclick="send()">提交</button>
<h3>状态</h3>
<pre id="s">等待…</pre>
<script>
async function send(){
  const b=document.getElementById('b'),t=document.getElementById('t');
  if(!t.value.trim())return;
  b.disabled=true;
  try{
    const r=await fetch('/c',{method:'POST',headers:{'Content-Type':'text/plain'},body:t.value.trim()});
    const d=await r.json();
    document.getElementById('s').textContent =
      `已接收 ${d.count} 次\\n本次 ${d.names.length} 项：${d.names.join(', ')}`+
      (d.has_uid?'':'\\n⚠️ 没有 _uid')+(d.has_vc3?'\\n✅ 含 vc3':'\\n⚠️ 没有 vc3');
    t.value='';
  }catch(e){document.getElementById('s').textContent='提交失败：'+e;}
  finally{b.disabled=false;}
}
</script>
"""


def make_handler(out_path, log) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        count = 0

        def log_message(self, fmt: str, *a) -> None:  # noqa: ANN002
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, b"", "text/plain")

        def do_GET(self) -> None:  # noqa: N802
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            text = self.rfile.read(length).decode("utf-8", "replace").strip()
            if text.startswith("{"):
                try:
                    data = json.loads(text)
                    if isinstance(data.get("cookies"), dict):
                        text = "; ".join(f"{k}={v}" for k, v in data["cookies"].items())
                    else:
                        text = str(data.get("cookie") or data.get("value") or text)
                except json.JSONDecodeError:
                    pass

            Handler.count += 1
            names = sorted(
                seg.split("=", 1)[0].strip() for seg in text.replace("\n", ";").split(";") if "=" in seg
            )
            has_vc3 = "vc3" in names
            if text:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text, encoding="utf-8")
                log(f"[{datetime.now():%H:%M:%S}] 收到 {len(names)} 项：{', '.join(names)}")
                if "vc3" not in names:
                    log("  !! 缺少 vc3 —— 请从 Network 面板复制 Cookie 请求头")

            body = json.dumps(
                {
                    "ok": True,
                    "count": Handler.count,
                    "names": names,
                    "has_uid": "_uid" in names or "UID" in names,
                    "has_vc3": has_vc3,
                },
                ensure_ascii=False,
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")

    return Handler


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    settings = Settings.load(args.config)
    out_path = settings.data_dir / "caught_cookie.txt"
    log = lambda msg: print(msg, flush=True)  # noqa: E731

    server = ThreadingHTTPServer((args.host, args.port), make_handler(out_path, log))
    print(f"接收器：http://{args.host}:{args.port}/")
    print(f"结果写入：{out_path.resolve()}")
    print("浏览器打开上面地址即可粘贴。Ctrl+C 退出。")

    if args.timeout > 0:
        threading.Thread(
            target=lambda: (time.sleep(args.timeout), server.shutdown()), daemon=True
        ).start()

    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        server.server_close()
    return 0
