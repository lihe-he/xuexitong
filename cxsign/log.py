"""日志初始化：控制台 + 轮转文件。

CLI 和 Web 服务共用一套，避免两边日志格式不一致。

    setup(verbose=True, log_dir=Path("data/logs"))

文件按 5MB 切分、保留 5 份，`data/logs/cxsign.log`。容器里看 stdout 即可，
文件日志主要给长期运行的监听模式和事后排查用。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup(
    *,
    verbose: bool = False,
    log_dir: str | Path | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backups: int = 5,
) -> logging.Logger:
    global _configured

    root = logging.getLogger("cxsign")
    level = logging.DEBUG if verbose else logging.INFO
    root.setLevel(level)

    if _configured:
        return root

    formatter = logging.Formatter(FORMAT, DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    if log_dir is not None:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path / "cxsign.log",
            maxBytes=max_bytes,
            backupCount=backups,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)

    root.propagate = False
    _configured = True
    return root


def reset() -> None:
    """测试用：拆掉所有 handler，允许重新配置。"""
    global _configured
    root = logging.getLogger("cxsign")
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _configured = False
