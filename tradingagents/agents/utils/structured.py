"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _thinking_off_clone(llm: Any) -> Any:
    """DeepSeek V4：structured 输出需要 tool_choice，而 thinking 模式不着用该参数（官方 400
    'Thinking mode does not support this tool_choice'）。克隆一个关闭 thinking 的同模型实例，
    使 with_structured_output(function_calling) 可用且更快；非 DeepSeek 或克隆失败时原样返回。
    """
    try:
        from tradingagents.llm_clients.openai_client import DeepSeekChatOpenAI

        if not isinstance(llm, DeepSeekChatOpenAI):
            return llm
        kwargs: dict = {
            "model": getattr(llm, "model_name", None),
            "api_key": getattr(llm, "openai_api_key", None),
            "temperature": getattr(llm, "temperature", 0.2),
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "openai_api_base_url", None)
        if base_url:
            kwargs["base_url"] = base_url
        max_tokens = getattr(llm, "max_tokens", None)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        clone = DeepSeekChatOpenAI(**kwargs)
        logger.info("DeepSeek structured：克隆 thinking-disabled 实例 model=%s", kwargs["model"])
        return clone
    except Exception as e:
        logger.warning("structured thinking-off 克隆失败，退回原 llm: %s", e)
        return llm


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return _thinking_off_clone(llm).with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content


def invoke_structured_dual(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> Tuple[Optional[T], str]:
    """Dual-write variant: return ``(structured_object|None, rendered_text)``.

    与 invoke_structured_or_freetext 行为一致，但额外保留结构化对象本身
    （供消费端直接读取，替代对渲染文本的正则重复解析）。结构化调用失败时
    回退自由文本，此时返回 (None, fallback_text)，消费端应退化到文本解析。
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return result, render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return None, response.content
