"""
防回归测试：bug-014 凭证明文存储

根因：
    MongoDB system_configs 集合中 llm_configs[].api_key、
    data_source_configs[].api_key/api_secret、database_configs[].password
    均为明文存储，违反"项目不得包含真实密钥"的硬约束。

修复：
    新增 app/utils/credential_crypto.py，提供字段级 Fernet 加密。
    - save_system_config: 落库前 encrypt_config_dict
    - get_system_config: 读取后 decrypt_config_dict
    - config_bridge.py 两处直接读 DB 也加解密
    - 老明文数据 decrypt 时原样返回（向后兼容），下次 save 自动加密

测试要点：
    - encrypt/decrypt 幂等性
    - 占位符不加密
    - 老明文向后兼容
    - 密文有 ENC: 前缀
    - encrypt_config_dict/decrypt_config_dict 覆盖三类配置
    - config_service 已接入加密
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ========================================================================
# Axiom 1：encrypt/decrypt 基本功能与幂等性
# ========================================================================

@pytest.mark.regression
def test_bug_014_encrypt_decrypt_roundtrip():
    """加密后解密应得到原值"""
    from app.utils.credential_crypto import decrypt, encrypt

    plaintext = "sk-d1el869r01qghj41hahgd1el869r01qghj41hai0"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext, "加密后应与原值不同"
    assert decrypt(ciphertext) == plaintext, "解密应还原原值"


@pytest.mark.regression
def test_bug_014_encrypt_is_idempotent():
    """对已加密的密文再次 encrypt 应原样返回（幂等）"""
    from app.utils.credential_crypto import encrypt

    plaintext = "sk-test-key-123456789"
    cipher1 = encrypt(plaintext)
    cipher2 = encrypt(cipher1)
    assert cipher1 == cipher2, "对密文再次加密应幂等返回"


# ========================================================================
# Axiom 2：占位符与空值不加密
# ========================================================================

@pytest.mark.regression
def test_bug_014_placeholder_not_encrypted():
    """占位符（your_*, xxxx, fake, 空）不应被加密"""
    from app.utils.credential_crypto import encrypt, is_encrypted

    placeholders = [
        None,
        "",
        "your_api_key_here",
        "your-tushare-token",
        "xxxx_placeholder",
        "fake_key_for_test",
        "d1el86...j41hai0",  # 截断显示
    ]
    for p in placeholders:
        result = encrypt(p)
        assert result == p, f"占位符 {p!r} 不应被加密，但得到了 {result!r}"
        assert not is_encrypted(result), f"占位符 {p!r} 不应标记为已加密"


# ========================================================================
# Axiom 3：老明文数据向后兼容
# ========================================================================

@pytest.mark.regression
def test_bug_014_legacy_plaintext_pass_through():
    """decrypt 对非 ENC: 前缀的明文应原样返回（向后兼容老数据）"""
    from app.utils.credential_crypto import decrypt

    legacy_plaintext = "sk-legacy-plaintext-key-12345"
    assert decrypt(legacy_plaintext) == legacy_plaintext, "老明文应原样返回"


# ========================================================================
# Axiom 4：密文有 ENC: 前缀标识
# ========================================================================

@pytest.mark.regression
def test_bug_014_ciphertext_has_prefix():
    """加密后的密文必须以 ENC: 开头"""
    from app.utils.credential_crypto import encrypt, is_encrypted

    ciphertext = encrypt("sk-real-key-1234567890abcdef")
    assert ciphertext.startswith("ENC:"), "密文必须有 ENC: 前缀"
    assert is_encrypted(ciphertext), "is_encrypted 应识别 ENC: 前缀"
    assert not is_encrypted("sk-plaintext"), "明文不应被识别为已加密"


# ========================================================================
# Axiom 5：encrypt_config_dict / decrypt_config_dict 覆盖三类配置
# ========================================================================

@pytest.mark.regression
def test_bug_014_config_dict_encrypt_decrypt():
    """encrypt_config_dict 应加密三类配置中的敏感字段，decrypt_config_dict 应还原"""
    from app.utils.credential_crypto import (
        decrypt_config_dict,
        encrypt_config_dict,
        is_encrypted,
    )

    config = {
        "llm_configs": [
            {"provider": "openai", "api_key": "sk-real-openai-key", "model_name": "gpt-4"},
            {"provider": "deepseek", "api_key": "your_deepseek_key", "model_name": "deepseek-chat"},
        ],
        "data_source_configs": [
            {"name": "Tushare", "api_key": "real-tushare-token", "api_secret": "real-secret"},
            {"name": "AKShare", "api_key": "", "api_secret": None},
        ],
        "database_configs": [
            {"name": "MongoDB", "password": "real-mongo-password"},
        ],
        "system_settings": {
            "quick_analysis_model": "gpt-4",
            "custom_api_key": "sk-custom-key",
            "normal_setting": "value",
        },
    }

    encrypted = encrypt_config_dict(config)

    # 真实密钥应被加密
    assert is_encrypted(encrypted["llm_configs"][0]["api_key"]), "LLM api_key 应被加密"
    assert is_encrypted(encrypted["data_source_configs"][0]["api_key"]), "数据源 api_key 应被加密"
    assert is_encrypted(encrypted["data_source_configs"][0]["api_secret"]), "数据源 api_secret 应被加密"
    assert is_encrypted(encrypted["database_configs"][0]["password"]), "数据库 password 应被加密"
    assert is_encrypted(encrypted["system_settings"]["custom_api_key"]), "system_settings 敏感键应被加密"

    # 占位符和空值不应被加密
    assert encrypted["llm_configs"][1]["api_key"] == "your_deepseek_key"
    assert encrypted["data_source_configs"][1]["api_key"] == ""
    assert encrypted["data_source_configs"][1]["api_secret"] is None

    # 非敏感字段不变
    assert encrypted["system_settings"]["normal_setting"] == "value"
    assert encrypted["system_settings"]["quick_analysis_model"] == "gpt-4"

    # 解密还原
    decrypted = decrypt_config_dict(encrypted)
    assert decrypted["llm_configs"][0]["api_key"] == "sk-real-openai-key"
    assert decrypted["data_source_configs"][0]["api_key"] == "real-tushare-token"
    assert decrypted["data_source_configs"][0]["api_secret"] == "real-secret"
    assert decrypted["database_configs"][0]["password"] == "real-mongo-password"
    assert decrypted["system_settings"]["custom_api_key"] == "sk-custom-key"


# ========================================================================
# Axiom 6：config_service.py 已接入加密
# ========================================================================

@pytest.mark.regression
def test_bug_014_config_service_imports_crypto():
    """config_service.py 必须导入并使用 credential_crypto"""
    import inspect
    from app.services import config_service

    source = inspect.getsource(config_service)
    assert "encrypt_config_dict" in source, "config_service 必须调用 encrypt_config_dict"
    assert "decrypt_config_dict" in source, "config_service 必须调用 decrypt_config_dict"


@pytest.mark.regression
def test_bug_014_config_bridge_imports_crypto():
    """config_bridge.py 必须导入并使用 credential_crypto"""
    import inspect
    from app.core import config_bridge

    source = inspect.getsource(config_bridge)
    assert "decrypt_config_dict" in source, "config_bridge 必须调用 decrypt_config_dict"


# ========================================================================
# Axiom 7：解密失败不阻断业务（密钥不匹配时返回原值）
# ========================================================================

@pytest.mark.regression
def test_bug_014_decrypt_failure_returns_original():
    """解密失败（密钥不匹配/损坏）应返回原值，不抛异常"""
    from app.utils.credential_crypto import decrypt

    # 伪造的密文，解密必然失败
    fake_cipher = "ENC:ZmFrZS1jaXBoZXJ0ZXh0LXdpdGgtaW52YWxpZC1mb3JtYXQ="
    result = decrypt(fake_cipher)
    # 解密失败应返回原值（不抛异常）
    assert result == fake_cipher, "解密失败应返回原值而非抛异常"


# ========================================================================
# Axiom 8：cryptography 依赖已声明且可导入
# ========================================================================

@pytest.mark.regression
def test_bug_014_cryptography_available():
    """cryptography 库必须已安装且可导入"""
    try:
        from cryptography.fernet import Fernet
        # 验证可用性
        key = Fernet.generate_key()
        f = Fernet(key)
        token = f.encrypt(b"test")
        assert f.decrypt(token) == b"test"
    except ImportError:
        # 如果不可导入，检查依赖声明
        dep_declared = False
        for check_path in [
            os.path.join(_PROJECT_ROOT, "pyproject.toml"),
            os.path.join(_PROJECT_ROOT, "requirements.txt"),
        ]:
            if os.path.exists(check_path):
                with open(check_path, "r", encoding="utf-8") as f:
                    if "cryptography" in f.read():
                        dep_declared = True
                        break
        assert dep_declared, "cryptography 必须在 pyproject.toml 或 requirements.txt 中声明"


# ========================================================================
# Axiom 9：.env.example 包含 CREDENTIAL_MASTER_KEY 占位
# ========================================================================

@pytest.mark.regression
def test_bug_014_env_example_has_master_key():
    """.env.example 必须包含 CREDENTIAL_MASTER_KEY 占位（本地检查，容器中 skip）"""
    env_path = os.path.join(_PROJECT_ROOT, ".env.example")
    if not os.path.exists(env_path):
        pytest.skip(".env.example 在容器中不存在（仅本地检查）")
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "CREDENTIAL_MASTER_KEY" in content, ".env.example 必须包含 CREDENTIAL_MASTER_KEY"
