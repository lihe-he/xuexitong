"""``python -m cxsign.tools`` 的入口。

    python -m cxsign.tools status                 当前账号/课程/配置/签到记录
    python -m cxsign.tools live --user U --password P
                                                  登录并跑只读链路
    python -m cxsign.tools diag                   诊断登录态、缺哪个 cookie
    python -m cxsign.tools probe [--qr]           探测接口是否存在
    python -m cxsign.tools qr --dir data/qr       二维码抢签（监听目录）
    python -m cxsign.tools qr --once shot.png     二维码抢签（单张）
    python -m cxsign.tools browser [--scan]       从浏览器 profile 导出 cookie
    python -m cxsign.tools catcher [--port 8765]  本地 cookie 接收器

每个子模块只暴露 ``run(args) -> int``，参数解析统一在这里做，
避免 14 个脚本各自一套 argparse。
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cxsign.tools", description="cxsign 运维与诊断工具")
    p.add_argument("-c", "--config", default="config.toml", help="配置文件路径")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="当前状态总览")

    sp = sub.add_parser("live", help="真实登录 + 只读链路验证（不提交签到）")
    sp.add_argument("--user", required=True, help="手机号")
    sp.add_argument("--password", required=True, help="密码")

    sub.add_parser("diag", help="诊断登录态：哪些域能用、缺哪个 cookie")

    sp = sub.add_parser("probe", help="探测接口存在性（未登录也能跑）")
    sp.add_argument("--qr", action="store_true", help="只探测二维码相关路径")

    sp = sub.add_parser("qr", help="二维码抢签")
    sp.add_argument("--once", help="处理单张图片后退出")
    sp.add_argument("--dir", default="", help="监听目录")
    sp.add_argument("--interval", type=float, default=0.0)
    sp.add_argument("--active", default="", help="已知 activeId")
    sp.add_argument("--course", default="", help="courseId")
    sp.add_argument("--class-id", default="", help="classId")

    sp = sub.add_parser("browser", help="从本机 Chromium profile 导出学习通 cookie")
    sp.add_argument("--profile", help="指定 profile 目录（默认 DSH 桌面端）")
    sp.add_argument("--scan", action="store_true", help="扫描全机所有 profile")
    sp.add_argument("--show", action="store_true", help="打印 cookie 值（脱敏）")

    sp = sub.add_parser("catcher", help="本地 cookie 接收器（带粘贴框）")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--timeout", type=int, default=0, help="多少秒后退出，0 = 常驻")

    return p


#: 子命令 → 模块名（延迟导入，避免没用到的模块拖慢启动）
DISPATCH = {
    "status": "status",
    "live": "live",
    "diag": "diag",
    "probe": "probe",
    "qr": "qr",
    "browser": "browser",
    "catcher": "catcher",
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    module = __import__(f"cxsign.tools.{DISPATCH[args.command]}", fromlist=["run"])
    return int(module.run(args))


if __name__ == "__main__":
    sys.exit(main())
