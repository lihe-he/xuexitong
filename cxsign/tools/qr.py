"""二维码抢签：截图落地 → 本地解码 → 立刻提交，全程计时。

## 为什么这么做

二维码签到的 ``enc`` 只存在于老师屏幕的动态码里，服务端**没有**任何
"凭 activeId 换 enc" 的接口（实测 10 条候选路径全部 tengine 500）。
所以唯一的杠杆是**缩短从看到码到提交的时间**。

## 三种用法

    python -m cxsign.tools qr --once shot.png
    python -m cxsign.tools qr --dir data/qr
    python -m cxsign.tools qr --once shot.png --active <id> --course <cid> --class-id <clsid>

第二种配合 Syncthing / 微信文件传输助手 / adb push 都能用，
从截屏到提交通常在 1~2 秒。

## 关键事实

* 同一个 ``enc`` **不绑学生**：老师屏幕上那一张，谁扫都能用。
  所以多账号只需要捕获一次，其余复用缓存。
* ``enc`` 会过期，过期后服务端返回 ``签到失败，请重新扫描``。
  本脚本会把实际年龄打进日志（TTL 观测）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from .. import qrdecode
from ..activity import Activity, SignKind
from ..config import Settings
from ..course import Course
from ..net import CxError
from ..runtime import build
from ..signer import SignOptions

IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _targets(rt, account, active_id="", course_id="", class_id="") -> list[Activity]:
    """优先用监听缓存的目标（秒级），缓存空才走全量扫描（10 秒级）。"""
    cached = rt.store.get_qr_targets(account.id)
    if active_id:
        cached = [c for c in cached if c["active_id"] == active_id]
        if not cached and course_id and class_id:
            return [Activity(active_id, "(manual)", Course(course_id, class_id), SignKind.QRCODE)]

    if cached:
        return [
            Activity(c["active_id"], "(cached)", Course(c["course_id"], c["class_id"]), SignKind.QRCODE)
            for c in cached
        ]

    activities = rt.engine.scan(account.id, use_backoff=False)
    qrs = [a for a in activities if a.kind is SignKind.QRCODE]
    for act in qrs:
        rt.store.save_qr_target(account.id, act.active_id, act.course.course_id, act.course.class_id)
    return qrs


def sign_all(rt, enc, *, source="", active_id="", course_id="", class_id="") -> int:
    ok_count = 0
    for account in rt.store.list_accounts(only_enabled=True):
        t_lookup = time.monotonic()
        try:
            targets = _targets(rt, account, active_id, course_id, class_id)
        except CxError as exc:
            print(f"  [{account.username}] 扫描失败：{exc}")
            continue

        if not targets:
            print(f"  [{account.username}] 没有二维码签到")
            continue
        print(f"  [{account.username}] 定位耗时 {(time.monotonic() - t_lookup) * 1000:.0f}ms")

        for act in targets:
            t0 = time.monotonic()
            rt.store.save_enc(act.active_id, enc, source=source)
            try:
                result = rt.engine.sign(account.id, act, SignOptions(enc=enc))
            except CxError as exc:
                print(f"  [{account.username}] 提交异常：{exc}")
                continue
            elapsed = time.monotonic() - t0
            flag = "✅" if result.ok else "❌"
            print(
                f"  [{account.username}] {flag} {result.message}  "
                f"({elapsed * 1000:.0f}ms)  active={act.active_id}"
            )
            if result.ok:
                ok_count += 1
                info = rt.store.enc_info(act.active_id)
                print(f"      └ enc 缓存 {info['age'] if info else 0}s 后仍有效（TTL 观测）")
    return ok_count


def handle_image(rt, path: Path, active_id="", course_id="", class_id="") -> bool:
    t_start = time.monotonic()
    try:
        enc = qrdecode.decode_enc(path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 解码失败 {path.name}: {exc}")
        return False

    print(f"  enc = {enc}  （解码耗时 {(time.monotonic() - t_start) * 1000:.0f}ms）")
    ok = sign_all(rt, enc, source=path.name, active_id=active_id,
                  course_id=course_id, class_id=class_id)
    print(f"  总耗时 {(time.monotonic() - t_start) * 1000:.0f}ms，成功 {ok} 个")
    return ok > 0


def watch(rt, directory: Path, interval: float, archive: Path, **kw) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    print(f"监听 {directory.resolve()} …")
    print("把二维码截图放进该目录即自动抢签。Ctrl+C 退出。")

    seen: set[str] = set()
    try:
        while True:
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIX:
                    continue
                key = f"{path.name}:{path.stat().st_mtime_ns}"
                if key in seen:
                    continue
                seen.add(key)
                print(f"\n[{time.strftime('%H:%M:%S')}] 发现 {path.name}")
                handle_image(rt, path, **kw)
                try:
                    shutil.move(str(path), archive / path.name)
                except OSError:
                    pass
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出")


def run(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    settings = Settings.load(args.config)
    if not qrdecode.available():
        print("缺少二维码解码依赖：pip install -e \".[qr]\"")
        return 1

    rt = build(settings)
    try:
        kw = {"active_id": args.active, "course_id": args.course, "class_id": args.class_id}
        if args.once:
            path = Path(args.once)
            if not path.is_file():
                print(f"图片不存在：{path}")
                return 1
            return 0 if handle_image(rt, path, **kw) else 2

        directory = Path(args.dir or settings.qr_watch_dir)
        watch(rt, directory, args.interval or settings.qr_poll_interval,
              directory / "_done", **kw)
        return 0
    finally:
        rt.close()
