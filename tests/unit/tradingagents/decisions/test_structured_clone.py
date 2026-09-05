"""structured 绑定：DeepSeek thinking-off 克隆行为单测。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/decisions/test_structured_clone.py
"""

from __future__ import annotations

from unittest import mock

from tradingagents.agents.utils.structured import _thinking_off_clone


class _PlainLLM:
    """非 DeepSeek 的普通 LLM（应原样返回）。"""


class _FakeDeepSeek:
    """真实替身类（type），捕获构造 kwargs；isinstance 对真类成立。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeDeepSeekFail:
    """构造必抛错的替身类。"""

    def __init__(self, **kwargs):
        raise TypeError("boom")


def test_non_deepseek_llm_returned_unchanged():
    plain = _PlainLLM()
    # 非 DeepSeek 类型 → 原样返回（不触发任何克隆）
    assert _thinking_off_clone(plain) is plain


def test_deepseek_clone_has_thinking_disabled():
    import tradingagents.llm_clients.openai_client as oc

    with mock.patch.object(oc, "DeepSeekChatOpenAI", _FakeDeepSeek) as fake_cls:
        llm = fake_cls()
        llm.model_name = "deepseek-v4-pro"
        llm.openai_api_key = "sk-fake"
        llm.openai_api_base = "https://api.deepseek.com"
        llm.temperature = 0.3
        llm.max_tokens = 4096

        clone = _thinking_off_clone(llm)
        assert isinstance(clone, _FakeDeepSeek) and clone is not llm
        kw = clone.kwargs
        assert kw["model"] == "deepseek-v4-pro"
        assert kw["api_key"] == "sk-fake"
        assert kw["temperature"] == 0.3
        assert kw["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kw["base_url"] == "https://api.deepseek.com"
        assert kw["max_tokens"] == 4096


def test_deepseek_clone_falls_back_to_custom_base_url():
    import tradingagents.llm_clients.openai_client as oc

    with mock.patch.object(oc, "DeepSeekChatOpenAI", _FakeDeepSeek) as fake_cls:
        llm = fake_cls()
        llm.model_name = "deepseek-v4-flash"
        llm.openai_api_key = "sk-fake"
        llm.openai_api_base = None
        llm.openai_api_base_url = "https://custom.example.com/v1"
        llm.temperature = 0.1
        llm.max_tokens = None

        clone = _thinking_off_clone(llm)
        assert clone.kwargs["base_url"] == "https://custom.example.com/v1"
        assert "max_tokens" not in clone.kwargs


def test_clone_failure_falls_back_to_original():
    import tradingagents.llm_clients.openai_client as oc

    with mock.patch.object(oc, "DeepSeekChatOpenAI", _FakeDeepSeekFail):
        # 用 __new__ 绕过抛错的 __init__ 构造出"DeepSeek 实例"
        llm = object.__new__(_FakeDeepSeekFail)
        llm.model_name = "deepseek-v4-pro"
        llm.openai_api_key = "sk-fake"
        llm.openai_api_base = None
        llm.temperature = 0.3
        llm.max_tokens = None
        assert _thinking_off_clone(llm) is llm