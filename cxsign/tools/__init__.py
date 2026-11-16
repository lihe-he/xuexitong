"""运维与诊断工具集。

统一入口：``python -m cxsign.tools <子命令>``。

拆分原则：

* **日常用的**（status / live / qr）放进主流程，有测试覆盖
* **诊断用的**（diag / probe / browser）保留但不参与主流程，
  出问题时能快速定位是"协议变了"还是"账号掉了"
* **一次性的**（dump_html 系列）直接删掉，需要时再用 ``probe`` 抓

所有子命令共用主包的 Settings / Runtime，不重复实现配置加载。
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from .__main__ import main as _main

    return _main(argv)
