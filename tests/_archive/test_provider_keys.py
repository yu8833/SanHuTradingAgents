import unittest

from tradingagents.llm_clients.provider_keys import (
    canonical_aliases,
    default_backend_url,
    env_key_for_provider,
    normalize_provider_key,
)


class ProviderKeysTests(unittest.TestCase):
    def test_normalize_dashscope_to_qwen(self):
        assert normalize_provider_key("dashscope") == "qwen"
        assert normalize_provider_key("阿里百炼") == "qwen"

    def test_normalize_zhipu_to_glm(self):
        assert normalize_provider_key("zhipu") == "glm"
        assert normalize_provider_key("智谱AI") == "glm"

    def test_env_key_mapping(self):
        assert env_key_for_provider("qwen") == "DASHSCOPE_API_KEY"
        assert env_key_for_provider("dashscope") == "DASHSCOPE_API_KEY"
        assert env_key_for_provider("glm") == "ZHIPU_API_KEY"

    def test_default_backend_url_mapping(self):
        assert "dashscope.aliyuncs.com" in default_backend_url("qwen")
        assert "open.bigmodel.cn" in default_backend_url("glm")

    def test_canonical_aliases(self):
        assert "dashscope" in canonical_aliases("qwen")
        assert "zhipu" in canonical_aliases("glm")


if __name__ == "__main__":
    unittest.main()
