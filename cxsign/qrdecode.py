"""二维码截图解码（可选依赖）。

为什么放这里：二维码签到的 ``enc`` 只能从老师的动态二维码里拿。人工扫码是
兜底，但更好的体验是**上传一张截图**，服务端直接解出 ``enc``。

实现两档，按可用性自动选择：

1. ``opencv-python`` 的 ``QRCodeDetector`` —— 纯 pip 安装，无额外 DLL，首选
2. 都没有时返回明确提示，前端引导用户手工粘贴

刻意**不接任何在线打码平台**：那会把 enc 和你的账号关联到第三方。
"""

from __future__ import annotations

import io
from pathlib import Path

from .signer.qrcode import extract_enc


class QrDecodeError(RuntimeError):
    pass


def _decode_opencv(data: bytes) -> str:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise QrDecodeError("图片无法解析，换一张截图试试")

    detector = cv2.QRCodeDetector()
    text, _points, _straight = detector.detectAndDecode(img)
    return (text or "").strip()


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def decode_text(image: bytes | str | Path) -> str:
    """把图片解成二维码原文。"""
    data = Path(image).read_bytes() if isinstance(image, (str, Path)) else image

    if not data:
        raise QrDecodeError("图片为空")

    if not available():
        raise QrDecodeError(
            "未安装二维码解码依赖，请执行 `pip install opencv-python-headless`，"
            "或直接在输入框粘贴扫码得到的文本"
        )

    try:
        return _decode_opencv(data)
    except QrDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise QrDecodeError(f"解码失败：{exc}") from exc


def decode_enc(image: bytes | str | Path) -> str:
    """一步到位：图片 → enc。解不出来就抛错，不返回空串。"""
    text = decode_text(image)
    if not text:
        raise QrDecodeError("图片里没有识别到二维码，换个角度重新截图")
    enc = extract_enc(text)
    if not enc:
        raise QrDecodeError(f"识别到内容但不是学习通二维码：{text[:120]}")
    return enc


def decode_stream(stream: io.BufferedIOBase) -> str:
    return decode_enc(stream.read())
