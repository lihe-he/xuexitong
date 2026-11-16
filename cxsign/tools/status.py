"""当前状态总览：账号、课程、配置、最近签到。"""

from __future__ import annotations

import argparse
import sys
import time

from ..config import Settings
from ..runtime import build


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    rt = build(Settings.load(args.config))
    try:
        print("=== 账号 ===")
        accounts = rt.store.list_accounts()
        if not accounts:
            print("  (无)")
        for a in accounts:
            mode = "密码" if a.password else ("Cookie" if a.cookies else "无凭证")
            print(
                f"  #{a.id}  {a.username}  {a.real_name or '-'}  "
                f"模式={mode}  cookie={len(a.cookies)}项  "
                f"device={a.device_code[:8] or '-'}  "
                f"出口={a.proxy or '直连'}  "
                f"{'启用' if a.enabled else '停用'}"
            )
            print(f"      课程缓存 {len(rt.store.list_courses(a.id))} 门")

        s = rt.settings
        print("\n=== 配置 ===")
        print(f"  数据目录   {s.data_dir.resolve()}")
        print(f"  密钥来源   {rt.secret.source}")
        print(f"  轮询间隔   {s.poll_interval}s   活动重试上限 {s.activity_ttl}s")
        print(f"  全局速率   {s.global_rate}/s（桶容量 {s.global_burst}）")
        print(f"  并发扫描   {s.scan_concurrency}")
        print(f"  身份隔离   {s.isolate_identity}   代理池 {len(s.proxy_pool)} 条")
        print(f"  反应抖动   {s.sign_delay_min}~{s.sign_delay_max}s，多账号错峰 +{s.multi_account_spread}s")
        print(f"  enc 复用   {s.enc_ttl}s")

        print("\n=== 最近签到 ===")
        rows = rt.store.logs_with_operator(10)
        if not rows:
            print("  (无记录)")
        for r in rows:
            ts = time.strftime("%m-%d %H:%M:%S", time.localtime(r["created_at"]))
            flag = "✅" if r["ok"] else "❌"
            print(f"  {ts}  {flag} [{r['kind']}] {r['message'][:40]}  active={r['active_id']}")
        return 0
    finally:
        rt.close()
