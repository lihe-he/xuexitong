"""``python -m cxsign.server`` 入口。"""

from __future__ import annotations

import argparse
import logging

from ..config import Settings


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    p = argparse.ArgumentParser(prog="cxsign-server", description="cxsign Web 服务")
    p.add_argument("-c", "--config", default="config.toml")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # 先加载配置，确保 data 目录存在再起 uvicorn
    Settings.load(args.config)
    uvicorn.run(
        "cxsign.server.main:app",
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
