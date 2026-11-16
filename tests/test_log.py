"""日志初始化测试。"""

from __future__ import annotations

import logging

from cxsign import log as cxlog


def test_setup_creates_rotating_file(tmp_path):
    cxlog.reset()
    root = cxlog.setup(verbose=True, log_dir=tmp_path)
    root.info("hello")
    for handler in root.handlers:
        handler.flush()
    logfile = tmp_path / "cxsign.log"
    assert logfile.is_file()
    assert "hello" in logfile.read_text(encoding="utf-8")
    cxlog.reset()


def test_setup_is_idempotent(tmp_path):
    cxlog.reset()
    first = cxlog.setup(log_dir=tmp_path)
    count = len(first.handlers)
    second = cxlog.setup(log_dir=tmp_path)          # 重复调用不应叠加 handler
    assert second is first
    assert len(second.handlers) == count
    cxlog.reset()


def test_reset_removes_handlers():
    cxlog.reset()
    root = cxlog.setup()
    assert root.handlers
    cxlog.reset()
    assert not logging.getLogger("cxsign").handlers


def test_console_only_without_log_dir():
    cxlog.reset()
    root = cxlog.setup(log_dir=None)
    assert len(root.handlers) == 1
    cxlog.reset()
