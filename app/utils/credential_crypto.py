"""
凭证加密模块

对 MongoDB 中存储的 API Key / Token / Secret 字段进行字段级对称加密，
避免明文落库。密文以 `ENC:` 前缀标识，解密时自动识别；老明文数据
在读取时原样返回（向后兼容），下次保存时自动加密。

主密钥来源（按优先级）：
1. 环境变量 CREDENTIAL_MASTER_KEY（生产推荐）
2. 环境变量 JWT_SECRET 派生（不改 .env 的兼容方式）
3. 进程内存随机生成（仅开发/测试，重启后老密文将无法解密）

约束：
- 占位符（your_*, xxxx, 空）不加密，原样返回
- 解密失败（密钥不匹配/损坏）返回原值，视为明文，不阻断业务
- 所有加解密均为同步操作，无 IO 依赖
"""
import base64
import hashlib
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# 密文前缀，用于区分密文与明文
_CIPHER_PREFIX = "ENC:"

# 占位符前缀，这些值不加密
_PLACEHOLDER_PREFIXES = ("your_", "your-", "xxxx", "fake", "test_")

# 单例 Fernet 实例与锁
_fernet_lock = threading.Lock()
_fernet_instance = None  # type: ignore
_temp_key_warned = False


def _derive_key(material: str) -> bytes:
    """从任意长度的密钥材料派生 32 字节 urlsafe base64 key（Fernet 要求）。"""
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet():
    """懒加载 Fernet 实例（线程安全单例）。"""
    global _fernet_instance, _temp_key_warned
    if _fernet_instance is not None:
        return _fernet_instance

    with _fernet_lock:
        if _fernet_instance is not None:
            return _fernet_instance

        # 1. 优先 CREDENTIAL_MASTER_KEY
        master_key = os.getenv("CREDENTIAL_MASTER_KEY", "").strip()
        if master_key:
            try:
                from cryptography.fernet import Fernet
                _fernet_instance = Fernet(_derive_key(master_key))
                logger.debug("凭证主密钥来源: CREDENTIAL_MASTER_KEY")
                return _fernet_instance
            except Exception as e:
                logger.warning(f"CREDENTIAL_MASTER_KEY 加载失败: {e}，尝试 fallback")

        # 2. Fallback: JWT_SECRET 派生（不改 .env 的兼容方式）
        jwt_secret = os.getenv("JWT_SECRET", "").strip()
        if jwt_secret and not jwt_secret.startswith("your-"):
            try:
                from cryptography.fernet import Fernet
                _fernet_instance = Fernet(_derive_key(jwt_secret))
                logger.info("凭证主密钥来源: JWT_SECRET 派生（推荐配置 CREDENTIAL_MASTER_KEY）")
                return _fernet_instance
            except Exception as e:
                logger.warning(f"JWT_SECRET 派生主密钥失败: {e}")

        # 3. 最后 fallback: 内存随机密钥（仅开发/测试，重启失效）
        if not _temp_key_warned:
            logger.warning(
                "⚠️ CREDENTIAL_MASTER_KEY 未配置且 JWT_SECRET 无效，"
                "使用临时内存密钥——重启后已加密的凭证将无法解密，"
                "请配置 CREDENTIAL_MASTER_KEY 环境变量"
            )
            _temp_key_warned = True
        try:
            from cryptography.fernet import Fernet
            _fernet_instance = Fernet(Fernet.generate_key())
        except ImportError:
            logger.error("cryptography 库未安装，凭证加密功能不可用")
            _fernet_instance = None
        return _fernet_instance


def _is_placeholder(value: str) -> bool:
    """判断是否是占位符（不加密）。"""
    if not value:
        return True
    v = value.strip()
    if not v:
        return True
    for prefix in _PLACEHOLDER_PREFIXES:
        if v.lower().startswith(prefix):
            return True
    # 截断显示的密钥也不加密
    if "..." in v:
        return True
    return False


def is_encrypted(value: Any) -> bool:
    """判断值是否是加密后的密文。"""
    if not isinstance(value, str):
        return False
    return value.startswith(_CIPHER_PREFIX)


def encrypt(plaintext: Any) -> Any:
    """加密一个值。

    - None / 空字符串 / 占位符 → 原样返回
    - 已加密的密文 → 原样返回（幂等）
    - 其他字符串 → 加密并加前缀
    """
    if plaintext is None:
        return None
    if not isinstance(plaintext, str):
        return plaintext
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext
    if _is_placeholder(plaintext):
        return plaintext

    f = _get_fernet()
    if f is None:
        # cryptography 不可用，降级为明文（不阻断业务）
        return plaintext

    try:
        token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_CIPHER_PREFIX}{token}"
    except Exception as e:
        logger.warning(f"加密失败，保留明文: {e}")
        return plaintext


def decrypt(ciphertext: Any) -> Any:
    """解密一个值。

    - None / 空字符串 / 占位符 → 原样返回
    - 非 ENC: 前缀 → 视为明文，原样返回（向后兼容老数据）
    - ENC: 前缀 → 解密；解密失败返回原值（不阻断业务）
    """
    if ciphertext is None:
        return None
    if not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext:
        return ciphertext
    if not is_encrypted(ciphertext):
        return ciphertext

    f = _get_fernet()
    if f is None:
        return ciphertext

    token_str = ciphertext[len(_CIPHER_PREFIX):]
    try:
        return f.decrypt(token_str.encode("ascii")).decode("utf-8")
    except Exception as e:
        # 解密失败（密钥不匹配/损坏）——视为明文，原样返回
        logger.debug(f"解密失败，视为明文: {e}")
        return ciphertext


# 需要加密的敏感字段配置
SENSITIVE_FIELDS_LLM = ["api_key"]
SENSITIVE_FIELDS_DATASOURCE = ["api_key", "api_secret", "token"]
SENSITIVE_FIELDS_DATABASE = ["password"]


def encrypt_config_dict(config_dict: dict) -> dict:
    """加密 SystemConfig.model_dump() 后的字典中的敏感字段。

    作用于 llm_configs / data_source_configs / database_configs 三个列表。
    原地修改并返回。
    """
    if not config_dict:
        return config_dict

    for llm in config_dict.get("llm_configs", []) or []:
        if isinstance(llm, dict):
            for field in SENSITIVE_FIELDS_LLM:
                if field in llm:
                    llm[field] = encrypt(llm[field])

    for ds in config_dict.get("data_source_configs", []) or []:
        if isinstance(ds, dict):
            for field in SENSITIVE_FIELDS_DATASOURCE:
                if field in ds:
                    ds[field] = encrypt(ds[field])

    for db_cfg in config_dict.get("database_configs", []) or []:
        if isinstance(db_cfg, dict):
            for field in SENSITIVE_FIELDS_DATABASE:
                if field in db_cfg:
                    db_cfg[field] = encrypt(db_cfg[field])

    # system_settings 中的敏感键也加密
    settings = config_dict.get("system_settings") or {}
    if isinstance(settings, dict):
        for k in list(settings.keys()):
            if any(p in k.lower() for p in ("api_key", "secret", "password", "token")):
                if isinstance(settings[k], str):
                    settings[k] = encrypt(settings[k])

    return config_dict


def decrypt_config_dict(config_dict: dict) -> dict:
    """解密从 MongoDB 读取的 SystemConfig 字典中的敏感字段。

    作用于 llm_configs / data_source_configs / database_configs 三个列表。
    原地修改并返回。
    """
    if not config_dict:
        return config_dict

    for llm in config_dict.get("llm_configs", []) or []:
        if isinstance(llm, dict):
            for field in SENSITIVE_FIELDS_LLM:
                if field in llm:
                    llm[field] = decrypt(llm[field])

    for ds in config_dict.get("data_source_configs", []) or []:
        if isinstance(ds, dict):
            for field in SENSITIVE_FIELDS_DATASOURCE:
                if field in ds:
                    ds[field] = decrypt(ds[field])

    for db_cfg in config_dict.get("database_configs", []) or []:
        if isinstance(db_cfg, dict):
            for field in SENSITIVE_FIELDS_DATABASE:
                if field in db_cfg:
                    db_cfg[field] = decrypt(db_cfg[field])

    settings = config_dict.get("system_settings") or {}
    if isinstance(settings, dict):
        for k in list(settings.keys()):
            if any(p in k.lower() for p in ("api_key", "secret", "password", "token")):
                if isinstance(settings[k], str):
                    settings[k] = decrypt(settings[k])

    return config_dict
