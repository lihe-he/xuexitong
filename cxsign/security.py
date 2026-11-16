"""凭据静态加密。

代签意味着库里躺着**别人的**密码，明文存储是不可接受的。这里用 Fernet
（AES-128-CBC + HMAC-SHA256）做静态加密，主密钥三级回退：

1. 环境变量 ``CXSIGN_SECRET``（推荐，容器 / systemd 注入）
2. ``<data_dir>/secret.key``（首次启动自动生成，权限 600）
3. 都拿不到就报错，**不会**静默降级成明文

存储格式带版本前缀 ``enc:v1:<fernet-token>``，方便以后换算法做在线迁移。
没有前缀的老数据按明文读取，并在下一次写入时自动升级。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
ENV_KEY = "CXSIGN_SECRET"


class SecretError(RuntimeError):
    """主密钥不可用 / 密文损坏。"""


class SecretBox:
    """绑定到某个 data_dir 的加解密器。"""

    def __init__(self, key: bytes, source: str = "unknown") -> None:
        self._fernet = Fernet(key)
        self.source = source

    # ------------------------------------------------------------ 构造
    @classmethod
    def load(cls, data_dir: str | Path, *, create: bool = True) -> SecretBox:
        env = os.environ.get(ENV_KEY, "").strip()
        if env:
            key = env.encode("ascii")
            try:
                return cls(key, source=f"env:{ENV_KEY}")
            except Exception as exc:  # noqa: BLE001
                raise SecretError(f"{ENV_KEY} 不是合法的 Fernet 密钥（应为 44 字节 base64）") from exc

        path = Path(data_dir) / "secret.key"
        if path.is_file():
            key = path.read_bytes().strip()
            try:
                return cls(key, source=f"file:{path}")
            except Exception as exc:  # noqa: BLE001
                raise SecretError(f"密钥文件损坏：{path}") from exc

        if not create:
            raise SecretError("找不到主密钥，且未允许自动生成")

        key = Fernet.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows 上 chmod 语义有限，忽略
        return cls(key, source=f"generated:{path}")

    # ------------------------------------------------------------ 读写
    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return PREFIX + token

    def decrypt(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith(PREFIX):
            return stored  # 兼容历史明文
        try:
            return self._fernet.decrypt(stored[len(PREFIX) :].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretError("密文无法解密，主密钥可能已更换") from exc

    @staticmethod
    def is_encrypted(value: str) -> bool:
        return bool(value) and value.startswith(PREFIX)


def mask(secret: str, keep: int = 2) -> str:
    """脱敏展示，给 UI 用。"""
    if not secret:
        return ""
    if len(secret) <= keep * 2:
        return "*" * len(secret)
    return secret[:keep] + "*" * (len(secret) - keep * 2) + secret[-keep:]
