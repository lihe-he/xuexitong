"""推送通道。

设计成"一个事件 → 多个通道"的扇出结构，新增通道只要写一个函数注册进
:data:`CHANNELS` 即可。

内置：
* ``webhook``   通用 POST JSON，接企业微信 / 钉钉 / 自建
* ``serverchan`` Server酱（微信）
* ``pushplus``  PushPlus（微信）
* ``telegram``  Telegram Bot
* ``console``   仅打印日志（默认）
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("cxsign.notify")

Sender = Callable[[dict[str, Any], dict[str, Any]], None]


def _post_json(url: str, payload: Any, timeout: float = 10.0) -> None:
    with httpx.Client(timeout=timeout) as client:
        client.post(url, json=payload)


def send_webhook(cfg: dict[str, Any], event: dict[str, Any]) -> None:
    url = cfg.get("url")
    if not url:
        return
    _post_json(url, event)


def send_serverchan(cfg: dict[str, Any], event: dict[str, Any]) -> None:
    key = cfg.get("sendkey")
    if not key:
        return
    url = f"https://sctapi.ftqq.com/{key}.send"
    with httpx.Client(timeout=10) as client:
        client.post(url, data={"title": event.get("title", "cxsign"), "desp": event.get("text", "")})


def send_pushplus(cfg: dict[str, Any], event: dict[str, Any]) -> None:
    token = cfg.get("token")
    if not token:
        return
    _post_json(
        "https://www.pushplus.plus/send",
        {
            "token": token,
            "title": event.get("title", "cxsign"),
            "content": event.get("text", ""),
            "template": "txt",
        },
    )


def send_telegram(cfg: dict[str, Any], event: dict[str, Any]) -> None:
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not (token and chat_id):
        return
    text = f"*{event.get('title', 'cxsign')}*\n{event.get('text', '')}"
    _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
    )


def send_console(cfg: dict[str, Any], event: dict[str, Any]) -> None:
    log.info("[notify] %s | %s", event.get("title"), event.get("text"))


CHANNELS: dict[str, Sender] = {
    "webhook": send_webhook,
    "serverchan": send_serverchan,
    "pushplus": send_pushplus,
    "telegram": send_telegram,
    "console": send_console,
}


def notify(config: dict[str, Any], title: str, text: str) -> None:
    """按配置扇出推送。任何通道异常都不影响主流程。"""
    event = {"title": title, "text": text}
    enabled = False
    for name, cfg in (config or {}).items():
        sender = CHANNELS.get(name)
        if sender is None or not isinstance(cfg, dict) or not cfg.get("enabled", True):
            continue
        enabled = True
        try:
            sender(cfg, event)
        except Exception as exc:  # noqa: BLE001
            log.warning("推送通道 %s 失败：%s", name, exc)
    if not enabled:
        log.info("[notify-off] %s | %s", title, text)


def dump(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False)
