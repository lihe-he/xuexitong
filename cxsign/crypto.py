"""学习通的密码加密参数。

学习通登录接口 `passport2.chaoxing.com/fanyalogin` 不接受明文密码，历史上有两套：

1. **AES-128-CBC / PKCS7 / base64**，key == iv == ``u2oh6Vu^HWe4_AES``（当前主用）
2. **DES-ECB / PKCS7 / hex**，key == ``u2oh6Vu^HWe40fj``（旧版，仍被部分入口接受）

本项目默认走 AES，失败时自动回退 DES。
"""

from __future__ import annotations

import base64
import binascii

from .config import AES_KEY, DES_KEY


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - len(data) % block
    return data + bytes([pad]) * pad


def aes_encrypt(plaintext: str, key: str = AES_KEY) -> str:
    """AES-128-CBC，key 与 iv 相同，输出 base64。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key_b = key.encode("utf-8")
    iv_b = key_b[:16].ljust(16, b"\0")
    encryptor = Cipher(algorithms.AES(key_b), modes.CBC(iv_b)).encryptor()
    body = _pkcs7_pad(plaintext.encode("utf-8"))
    ct = encryptor.update(body) + encryptor.finalize()
    return base64.b64encode(ct).decode("ascii")


def des_encrypt(plaintext: str, key: str = DES_KEY) -> str:
    """DES-ECB，输出大写 hex（与 crypto-js `DES.encrypt().ciphertext.toString()` 一致）。"""
    from Crypto.Cipher import DES

    cipher = DES.new(key.encode("utf-8")[:8], DES.MODE_ECB)
    ct = cipher.encrypt(_pkcs7_pad(plaintext.encode("utf-8"), 8))
    return binascii.hexlify(ct).decode("ascii").upper()


def encrypt_password(plaintext: str, scheme: str = "aes") -> str:
    """按指定方案加密；scheme in {"aes", "des"}。"""
    if scheme == "des":
        return des_encrypt(plaintext)
    return aes_encrypt(plaintext)
