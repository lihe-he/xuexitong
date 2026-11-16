"""命令行入口：``cxsign <command>``

    cxsign login   --user 138xxxxxxxx --password xxx
    cxsign courses --sync
    cxsign scan
    cxsign sign    --active 123456789
    cxsign sign    --active 123456789 --code 1234
    cxsign sign    --active 123456789 --enc 1D0A628CK317F44CCC378M5KD92
    cxsign monitor
"""

from __future__ import annotations

import argparse
import sys
import time

from .activity import SignKind, describe
from .config import Settings
from .engine import Engine
from .monitor import Monitor
from .signer import SignOptions
from .store import Store


def _setup_logging(verbose: bool = False, log_dir=None) -> None:
    from . import log as cxlog

    cxlog.setup(verbose=verbose, log_dir=log_dir)


def _build(args: argparse.Namespace) -> tuple[Settings, Store, Engine]:
    from .runtime import build

    settings = Settings.load(args.config)
    rt = build(settings)
    return rt.settings, rt.store, rt.engine


def _pick_account(store: Store, wanted: str | None):
    accounts = store.list_accounts()
    if not accounts:
        print("还没有账号，先跑：cxsign login --user <手机号> --password <密码>")
        sys.exit(1)
    if wanted:
        for a in accounts:
            if a.username == wanted:
                return a
        print(f"找不到账号 {wanted}")
        sys.exit(1)
    if len(accounts) == 1:
        return accounts[0]
    print("存在多个账号，用 --account <手机号> 指定：")
    for a in accounts:
        print(f"  {a.username}  {a.real_name}")
    sys.exit(1)


# ---------------------------------------------------------------- commands
def cmd_login(args: argparse.Namespace) -> int:
    _, store, engine = _build(args)
    try:
        info = engine.login_and_save(args.user, args.password)
    finally:
        engine.close()
        store.close()
    print(f"✅ 登录成功：{info['real_name'] or info['username']}（account_id={info['account_id']}）")
    return 0


def cmd_courses(args: argparse.Namespace) -> int:
    _, store, engine = _build(args)
    account = _pick_account(store, args.account)
    try:
        if args.sync:
            engine.sync_courses(account.id)
        courses = engine.cached_courses(account.id)
    finally:
        engine.close()
        store.close()
    if not courses:
        print("没有课程缓存，加 --sync 同步一次")
        return 1
    for c in courses:
        print(f"  {c.course_id}  {c.class_id}  {c.name or ''}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    _, store, engine = _build(args)
    account = _pick_account(store, args.account)
    try:
        activities = engine.scan(account.id, refresh_courses=args.sync)
    finally:
        engine.close()
        store.close()
    if not activities:
        print("当前没有进行中的签到")
        return 0
    print(f"发现 {len(activities)} 个进行中的签到：")
    for a in activities:
        hint = f"（需要 {a.needs_input}）" if a.needs_input else ""
        print(f"  {a.active_id}  {describe(a.kind)}{hint}  {a.course}  {a.name}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    settings, store, engine = _build(args)
    account = _pick_account(store, args.account)
    try:
        activities = engine.scan(account.id, refresh_courses=args.sync)
        target = None
        for a in activities:
            if a.active_id == args.active:
                target = a
                break
        if target is None:
            # 允许对已知 activeId 直接硬签（用于测试或已过期活动）
            from .activity import Activity
            from .course import Course

            if not args.course:
                print(f"在活动列表里找不到 {args.active}；若确定要硬签，请同时给 --course/--class-id")
                return 1
            target = Activity(
                active_id=args.active,
                name="manual",
                course=Course(course_id=args.course, class_id=args.class_id),
                kind=SignKind(args.kind or "plain"),
            )

        opts = SignOptions(
            name=args.name or account.real_name,
            sign_code=args.code or "",
            enc=args.enc or "",
            lat=args.lat or settings.default_lat,
            lon=args.lon or settings.default_lon,
            address=args.address or settings.default_address,
            object_id=args.object_id or "",
            extra={"photo_path": args.photo} if args.photo else {},
        )
        # 二维码：给了图片就先本地解码
        if args.qr_image and not opts.enc:
            from . import qrdecode

            try:
                opts.enc = qrdecode.decode_enc(args.qr_image)
                print(f"从图片解出 enc = {opts.enc}")
            except qrdecode.QrDecodeError as exc:
                print(f"二维码解码失败：{exc}")
                return 3

        result = engine.sign(account.id, target, opts)
    finally:
        engine.close()
        store.close()
    print(result)
    return 0 if result.ok else 2


def cmd_monitor(args: argparse.Namespace) -> int:
    settings, store, engine = _build(args)
    if args.interval:
        settings.poll_interval = args.interval

    accounts = store.list_accounts(only_enabled=True)
    if not accounts:
        print("没有启用的账号，先跑：cxsign login --user <手机号> --password <密码>")
        engine.close()
        store.close()
        return 1

    monitor = Monitor(settings, engine, auto_sign=not args.dry_run)
    monitor.start()
    print(f"监听 {len(accounts)} 个账号：{', '.join(a.username for a in accounts)}")
    print(f"每 {settings.poll_interval}s 扫一次，Ctrl+C 退出")

    # 预扫一次，尽早暴露登录态问题；失败不影响监听
    for account in accounts:
        try:
            engine.scan(account.id, refresh_courses=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  预扫描 {account.username} 失败（不影响监听）：{exc}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        monitor.stop()
        engine.close()
        store.close()
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    _, store, engine = _build(args)
    target = args.account_target or args.account
    if not target:
        engine.close()
        store.close()
        print("用 --account-target <手机号或ID> 指定要删除的账号")
        return 1
    account = store.get_account_by_name(target)
    if account is None and target.isdigit():
        account = store.get_account(int(target))
    if account is None:
        engine.close()
        store.close()
        print(f"找不到账号 {target}")
        return 1
    engine.drop_session(account.id)
    store.delete_account(account.id)
    engine.close()
    store.close()
    print(f"已删除账号 {account.username}（#{account.id}），签到日志保留")
    return 0


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cxsign", description="超星学习通自动签到")
    p.add_argument("-c", "--config", default="config.toml", help="配置文件路径")
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    p.add_argument("--account", help="多账号时指定手机号")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("login", help="登录并保存 Cookie")
    sp.add_argument("--user", required=True, help="手机号")
    sp.add_argument("--password", required=True)
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("courses", help="列出课程")
    sp.add_argument("--sync", action="store_true", help="先同步")
    sp.set_defaults(func=cmd_courses)

    sp = sub.add_parser("scan", help="扫描进行中的签到")
    sp.add_argument("--sync", action="store_true", help="先同步课程")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("sign", help="手动签一个")
    sp.add_argument("--active", required=True, help="activeId")
    sp.add_argument("--course", help="硬签时的 courseId")
    sp.add_argument("--class-id", default="", help="硬签时的 classId")
    sp.add_argument("--kind", default="", help="硬签时的类型：plain/gesture/location/photo/qrcode/signcode")
    sp.add_argument("--sync", action="store_true")
    sp.add_argument("--code", help="签到码")
    sp.add_argument("--enc", help="二维码 enc")
    sp.add_argument("--qr-image", help="二维码截图，自动解码出 enc")
    sp.add_argument("--lat", help="纬度（BD-09）")
    sp.add_argument("--lon", help="经度（BD-09）")
    sp.add_argument("--address", help="位置签到地址文字")
    sp.add_argument("--object-id", help="拍照签到 objectId")
    sp.add_argument("--photo", help="本地图片路径，自动上传云盘")
    sp.add_argument("--name", help="姓名，默认用账号真实姓名")
    sp.set_defaults(func=cmd_sign)

    sp = sub.add_parser("monitor", help="监听并自动签到")
    sp.add_argument("--interval", type=int, default=0, help="轮询间隔秒，默认取配置")
    sp.add_argument("--dry-run", action="store_true", help="只发现不签到")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("rm", help="删除账号（手机号或 ID）")
    sp.add_argument("account_target", nargs="?", help="手机号或 account_id")
    sp.add_argument("--account-target", dest="account_target", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_remove)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.config)
    _setup_logging(args.verbose, log_dir=settings.data_dir / "logs")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
