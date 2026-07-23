"""兼容层: provider_keys 工具"""
import os
from typing import Optional


# 提供商别名规范表
CANONICAL_ALIASES = {
    # OpenAI 兼容协议
    "openai": "openai",
    "gpt": "openai",
    "deepseek": "deepseek",
    "moonshot": "moonshot",
    "kimi": "moonshot",
    "zhipuai": "zhipuai",
    "glm": "zhipuai",
    "bigmodel": "zhipuai",
    "qwen": "qwen",  # 🔥 修复：qwen 应该映射到 qwen（factory.py 中已支持）
    "dashscope": "qwen",  # 🔥 修复：dashscope 也映射到 qwen
    "tongyi": "qwen",  # 🔥 修复：通义千问映射到 qwen
    "302ai": "302ai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "google": "google",
    "gemini": "google",
    "azure": "azure",
    "azure_openai": "azure",
    "ollama": "ollama",
    "openrouter": "openrouter",
}


# 厂家到环境变量名的映射
ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "zhipuai": "ZHIPUAI_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",  # 🔥 修复：qwen 使用 DASHSCOPE_API_KEY
    "dashscope": "DASHSCOPE_API_KEY",
    "302ai": "302AI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


# 默认 backend URL
DEFAULT_BACKEND_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipuai": "https://open.bigmodel.cn/api/paas/v4",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",  # 🔥 修复：qwen 使用阿里云 API
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "302ai": "https://api.302ai.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def normalize_provider_key(provider: str) -> str:
    """规范化提供商名称"""
    if not provider:
        return ""
    p = str(provider).strip().lower().replace("-", "_").replace(" ", "_")
    return CANONICAL_ALIASES.get(p, p)


def env_key_for_provider(provider: str) -> str:
    """获取提供商对应的环境变量名"""
    canonical = normalize_provider_key(provider)
    return ENV_KEY_MAP.get(canonical, f"{canonical.upper()}_API_KEY")


def default_backend_url(provider: str) -> Optional[str]:
    """获取提供商的默认 backend URL"""
    canonical = normalize_provider_key(provider)
    return DEFAULT_BACKEND_URLS.get(canonical)
