"""
简化的股票分析服务
直接调用现有的 TradingAgents 分析功能
"""

import asyncio
import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.timezone import now_tz, to_display_iso

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 初始化TradingAgents日志系统
from tradingagents.utils.logging_init import init_logging

init_logging()

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.analysis import AnalysisStatus, SingleAnalysisRequest
from app.models.notification import NotificationCreate
from app.models.user import PyObjectId
from app.services.config_service import ConfigService
from app.services.memory_state_manager import TaskStatus, get_memory_state_manager
from app.services.progress_log_handler import register_analysis_tracker, unregister_analysis_tracker
from app.services.redis_progress_tracker import RedisProgressTracker, get_progress_by_id
from app.routers.reports import recompute_confidence
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# 股票基础信息获取（用于补充显示名称）
try:
    from tradingagents.dataflows.data_source_manager import get_data_source_manager
    _data_source_manager = get_data_source_manager()
    def _get_stock_info_safe(stock_code: str):
        """获取股票基础信息的安全封装"""
        return _data_source_manager.get_stock_basic_info(stock_code)
except Exception:
    _get_stock_info_safe = None

# 设置日志
logger = logging.getLogger("app.services.simple_analysis_service")


def _extract_concise_summary(content: str, max_len: int = 120) -> str:
    """
    从分析报告内容中提取简明摘要，避免原始 Markdown 表格造成排版混乱。

    优先解析"质量评估摘要"表格中的关键指标（整体质量/置信度/建议参考），
    并追加表格后的风险提示段落；无法解析时回退为纯文本截断。

    Args:
        content: 原始分析内容（通常为 final_trade_decision 的 Markdown）
        max_len: 摘要最大长度

    Returns:
        简明摘要文本
    """
    if not isinstance(content, str) or not content.strip():
        return ""
    # 1. 解析 Markdown 表格中的关键指标
    kv: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in ("指标", "值", "", "---"):
                key = cells[0].strip("#* ")
                val = cells[1].strip("#* ")
                if key:
                    kv[key] = val
    parts = [f"{k}:{kv[k]}" for k in ("整体质量", "置信度", "建议参考") if k in kv]
    if parts:
        text = "; ".join(parts)
        # 2. 追加表格后的风险提示/说明段落
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("|") or line.startswith("#") or line.startswith("-"):
                continue
            if line.startswith(("📊", "⚠️", "⚠", "📈", "📉", "🎯", "✅")):
                continue
            if len(line) > 5:
                text += f"。{line}"
                break
        if len(text) > max_len:
            text = text[:max_len].rstrip() + "..."
        return text
    # 3. 无法解析表格时回退为纯文本截断
    text = content.replace("#", "").replace("*", "").strip()
    return text[:max_len].rstrip() + ("..." if len(text) > max_len else "")


def _sanitize_state_for_mongo(state: Any) -> Any:
    """
    清理 state 对象，移除不可序列化的 LangChain 消息对象，确保可以存入 MongoDB。

    递归遍历 state，将以下对象转换为可序列化格式：
    - LangChain Message 对象 (HumanMessage, AIMessage, ToolMessage, SystemMessage 等)
    - 其他不可序列化的自定义对象

    Args:
        state: 要清理的 state 对象

    Returns:
        清理后的可序列化对象
    """
    # 处理 None
    if state is None:
        return None

    # 处理基本类型
    if isinstance(state, (str, int, float, bool, datetime, ObjectId)):
        return state

    # 处理列表
    if isinstance(state, list):
        result = []
        for item in state:
            # 检查是否是 LangChain Message 对象
            if hasattr(item, 'content') and hasattr(item, 'type'):
                # 转换为字典
                msg_dict = {
                    'type': getattr(item, 'type', 'unknown'),
                    'content': str(getattr(item, 'content', '')),
                }
                # 保留 additional_kwargs 如果存在且可序列化
                if hasattr(item, 'additional_kwargs'):
                    try:
                        kwargs = getattr(item, 'additional_kwargs', {})
                        if isinstance(kwargs, dict):
                            msg_dict['additional_kwargs'] = kwargs
                    except Exception:
                        pass
                result.append(msg_dict)
            else:
                result.append(_sanitize_state_for_mongo(item))
        return result

    # 处理字典
    if isinstance(state, dict):
        result = {}
        for key, value in state.items():
            result[key] = _sanitize_state_for_mongo(value)
        return result

    # 处理有 __dict__ 属性的对象
    if hasattr(state, '__dict__'):
        try:
            return _sanitize_state_for_mongo(vars(state))
        except Exception:
            return str(state)

    # 其他类型，尝试转换为字符串
    try:
        return str(state)
    except Exception:
        return None

# 配置服务实例
config_service = ConfigService()


async def get_provider_by_model_name(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（异步版本）

    Args:
        model_name: 模型名称，如 'qwen-turbo', 'gpt-4' 等

    Returns:
        str: 供应商名称，如 'dashscope', 'openai' 等
    """
    try:
        # 从配置服务获取系统配置
        system_config = await config_service.get_system_config()
        if not system_config or not system_config.llm_configs:
            logger.warning("⚠️ 系统配置为空，使用默认供应商映射")
            return _get_default_provider_by_model(model_name)

        # 在LLM配置中查找匹配的模型
        for llm_config in system_config.llm_configs:
            if llm_config.model_name == model_name:
                provider = llm_config.provider.value if hasattr(llm_config.provider, 'value') else str(llm_config.provider)
                logger.info(f"✅ 从数据库找到模型 {model_name} 的供应商: {provider}")
                return provider

        # 如果数据库中没有找到，使用默认映射
        logger.warning(f"⚠️ 数据库中未找到模型 {model_name}，使用默认映射")
        return _get_default_provider_by_model(model_name)

    except Exception as e:
        logger.error(f"❌ 查找模型供应商失败: {e}")
        return _get_default_provider_by_model(model_name)


def get_provider_by_model_name_sync(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（同步版本）

    Args:
        model_name: 模型名称，如 'qwen-turbo', 'gpt-4' 等

    Returns:
        str: 供应商名称，如 'dashscope', 'openai' 等
    """
    provider_info = get_provider_and_url_by_model_sync(model_name)
    return provider_info["provider"]


def get_provider_and_url_by_model_sync(model_name: str) -> dict:
    """
    根据模型名称从数据库配置中查找对应的供应商和 API URL（同步版本）

    Args:
        model_name: 模型名称，如 'qwen-turbo', 'gpt-4' 等

    Returns:
        dict: {"provider": "google", "backend_url": "https://...", "api_key": "xxx"}
    """
    try:
        # 使用同步 MongoDB 客户端直接查询

        from pymongo import MongoClient

        from app.core.config import settings

        client = MongoClient(settings.MONGO_URI)
        db = client[settings.MONGO_DB]

        # 查询最新的活跃配置
        configs_collection = db.system_configs
        doc = configs_collection.find_one({"is_active": True}, sort=[("version", -1)])

        if doc and "llm_configs" in doc:
            llm_configs = doc["llm_configs"]

            for config_dict in llm_configs:
                if config_dict.get("model_name") == model_name:
                    provider = config_dict.get("provider")
                    api_base = config_dict.get("api_base")
                    model_api_key = config_dict.get("api_key")  # 🔥 获取模型配置的 API Key

                    # 从 llm_providers 集合中查找厂家配置
                    providers_collection = db.llm_providers
                    provider_doc = providers_collection.find_one({"name": provider})

                    # 🔥 确定 API Key（优先级：模型配置 > 厂家配置 > 环境变量）
                    api_key = None
                    if model_api_key and model_api_key.strip() and model_api_key != "your-api-key":
                        api_key = model_api_key
                        logger.info("✅ [同步查询] 使用模型配置的 API Key")
                    elif provider_doc and provider_doc.get("api_key"):
                        provider_api_key = provider_doc["api_key"]
                        if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
                            api_key = provider_api_key
                            logger.info("✅ [同步查询] 使用厂家配置的 API Key")

                    # 如果数据库中没有有效的 API Key，尝试从环境变量获取
                    if not api_key:
                        api_key = _get_env_api_key_for_provider(provider)
                        if api_key:
                            logger.info("✅ [同步查询] 使用环境变量的 API Key")
                        else:
                            logger.warning(f"⚠️ [同步查询] 未找到 {provider} 的 API Key")

                    # 确定 backend_url
                    backend_url = None
                    if api_base:
                        backend_url = api_base
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用自定义 API: {api_base}")
                    elif provider_doc and provider_doc.get("default_base_url"):
                        backend_url = provider_doc["default_base_url"]
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用厂家默认 API: {backend_url}")
                    else:
                        backend_url = _get_default_backend_url(provider)
                        logger.warning(f"⚠️ [同步查询] 厂家 {provider} 没有配置 default_base_url，使用硬编码默认值")

                    from tradingagents.llm_clients.provider_keys import default_backend_url, normalize_provider_key

                    provider_key = normalize_provider_key(provider)
                    if provider_key == "qwen" and backend_url == "https://dashscope.aliyuncs.com/api/v1":
                        backend_url = default_backend_url(provider_key)

                    client.close()
                    return {
                        "provider": provider_key,
                        "backend_url": backend_url,
                        "api_key": api_key
                    }

        client.close()

        # 如果数据库中没有找到模型配置，使用默认映射
        logger.warning(f"⚠️ [同步查询] 数据库中未找到模型 {model_name}，使用默认映射")
        provider = _get_default_provider_by_model(model_name)

        # 尝试从厂家配置中获取 default_base_url 和 API Key
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client[settings.MONGO_DB]
            providers_collection = db.llm_providers
            provider_doc = providers_collection.find_one({"name": provider})

            backend_url = _get_default_backend_url(provider)
            api_key = None

            if provider_doc:
                if provider_doc.get("default_base_url"):
                    backend_url = provider_doc["default_base_url"]
                    logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 default_base_url: {backend_url}")

                if provider_doc.get("api_key"):
                    provider_api_key = provider_doc["api_key"]
                    if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
                        api_key = provider_api_key
                        logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 API Key")

            # 如果厂家配置中没有 API Key，尝试从环境变量获取
            if not api_key:
                api_key = _get_env_api_key_for_provider(provider)
                if api_key:
                    logger.info("✅ [同步查询] 使用环境变量的 API Key")

            from tradingagents.llm_clients.provider_keys import default_backend_url, normalize_provider_key

            provider_key = normalize_provider_key(provider)
            if provider_key == "qwen" and backend_url == "https://dashscope.aliyuncs.com/api/v1":
                backend_url = default_backend_url(provider_key)

            client.close()
            return {
                "provider": provider_key,
                "backend_url": backend_url,
                "api_key": api_key
            }
        except Exception as e:
            logger.warning(f"⚠️ [同步查询] 无法查询厂家配置: {e}")

        # 最后回退到硬编码的默认 URL 和环境变量 API Key
        from tradingagents.llm_clients.provider_keys import normalize_provider_key

        provider_key = normalize_provider_key(provider)
        return {
            "provider": provider_key,
            "backend_url": _get_default_backend_url(provider_key),
            "api_key": _get_env_api_key_for_provider(provider_key)
        }

    except Exception as e:
        logger.error(f"❌ [同步查询] 查找模型供应商失败: {e}")
        provider = _get_default_provider_by_model(model_name)

        # 尝试从厂家配置中获取 default_base_url 和 API Key
        try:
            from pymongo import MongoClient

            from app.core.config import settings

            client = MongoClient(settings.MONGO_URI)
            db = client[settings.MONGO_DB]
            providers_collection = db.llm_providers
            provider_doc = providers_collection.find_one({"name": provider})

            backend_url = _get_default_backend_url(provider)
            api_key = None

            if provider_doc:
                if provider_doc.get("default_base_url"):
                    backend_url = provider_doc["default_base_url"]
                    logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 default_base_url: {backend_url}")

                if provider_doc.get("api_key"):
                    provider_api_key = provider_doc["api_key"]
                    if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
                        api_key = provider_api_key
                        logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 API Key")

            # 如果厂家配置中没有 API Key，尝试从环境变量获取
            if not api_key:
                api_key = _get_env_api_key_for_provider(provider)

            client.close()
            return {
                "provider": provider,
                "backend_url": backend_url,
                "api_key": api_key
            }
        except Exception as e2:
            logger.warning(f"⚠️ [同步查询] 无法查询厂家配置: {e2}")

        # 最后回退到硬编码的默认 URL 和环境变量 API Key
        return {
            "provider": provider,
            "backend_url": _get_default_backend_url(provider),
            "api_key": _get_env_api_key_for_provider(provider)
        }


def _get_env_api_key_for_provider(provider: str) -> str:
    """
    从环境变量获取指定供应商的 API Key

    Args:
        provider: 供应商名称，如 'google', 'dashscope' 等

    Returns:
        str: API Key，如果未找到则返回 None
    """
    import os

    from tradingagents.llm_clients.provider_keys import env_key_for_provider, normalize_provider_key

    provider_key = normalize_provider_key(provider)
    env_key_name = env_key_for_provider(provider_key)
    if not env_key_name and provider_key == "302ai":
        env_key_name = "AI302_API_KEY"
    if not env_key_name and provider_key == "aihubmix":
        env_key_name = "AIHUBMIX_API_KEY"
    if env_key_name:
        api_key = os.getenv(env_key_name)
        if api_key and api_key.strip() and api_key != "your-api-key":
            return api_key

    return None


def _get_default_backend_url(provider: str) -> str:
    """
    根据供应商名称返回默认的 backend_url

    Args:
        provider: 供应商名称，如 'google', 'dashscope' 等

    Returns:
        str: 默认的 backend_url
    """
    from tradingagents.llm_clients.provider_keys import default_backend_url, normalize_provider_key

    provider_key = normalize_provider_key(provider)
    if provider_key == "302ai":
        url = "https://api.302.ai/v1"
    elif provider_key == "aihubmix":
        url = "https://aihubmix.com/v1"
    else:
        url = default_backend_url(provider_key)

    logger.info(f"🔧 [默认URL] {provider} -> {url}")
    return url


def _get_default_provider_by_model(model_name: str) -> str:
    """
    根据模型名称返回默认的供应商映射
    这是一个后备方案，当数据库查询失败时使用
    """
    # 模型名称到供应商的默认映射
    model_provider_map = {
        # 阿里百炼 (DashScope)
        'qwen-turbo': 'qwen',
        'qwen-plus': 'qwen',
        'qwen-max': 'qwen',
        'qwen-plus-latest': 'qwen',
        'qwen-max-longcontext': 'qwen',

        # OpenAI
        'gpt-3.5-turbo': 'openai',
        'gpt-4': 'openai',
        'gpt-4-turbo': 'openai',
        'gpt-4o': 'openai',
        'gpt-4o-mini': 'openai',

        # Google
        'gemini-pro': 'google',
        'gemini-2.0-flash': 'google',
        'gemini-2.0-flash-thinking-exp': 'google',

        # DeepSeek
        'deepseek-chat': 'deepseek',
        'deepseek-coder': 'deepseek',

        # 智谱AI
        'glm-4': 'glm',
        'glm-3-turbo': 'glm',
        'chatglm3-6b': 'glm'
    }

    provider = model_provider_map.get(model_name, 'qwen')  # 默认使用阿里百炼
    logger.info(f"🔧 使用默认映射: {model_name} -> {provider}")
    return provider


def create_analysis_config(
    selected_analysts: list,
    quick_model: str,
    deep_model: str,
    llm_provider: str,
    market_type: str = "A股",
    quick_model_config: dict = None,
    deep_model_config: dict = None,
    mode: str = "full"
) -> dict:
    """
    创建分析配置

    Args:
        selected_analysts: 选中的分析师列表
        quick_model: 快速分析模型
        deep_model: 深度分析模型
        llm_provider: LLM供应商
        market_type: 市场类型
        quick_model_config: 快速模型的完整配置
        deep_model_config: 深度模型的完整配置
        mode: 分析模式，light=快评(精简链), full=尽调(完整链)

    Returns:
        dict: 完整的分析配置
    """
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = llm_provider
    config["deep_think_llm"] = deep_model
    config["quick_think_llm"] = quick_model

    # 🔧 获取 backend_url 和 API Key（优先级：模型配置 > 厂家配置 > 环境变量）
    try:
        quick_provider_info = get_provider_and_url_by_model_sync(quick_model)
        deep_provider_info = get_provider_and_url_by_model_sync(deep_model)

        config["backend_url"] = quick_provider_info["backend_url"]
        config["quick_api_key"] = quick_provider_info.get("api_key")
        config["deep_api_key"] = deep_provider_info.get("api_key")

        logger.info(f"✅ 使用数据库配置的 backend_url: {quick_provider_info['backend_url']}")
        logger.info(f"   来源: 模型 {quick_model} 的配置或厂家 {quick_provider_info['provider']} 的默认地址")
        logger.info(f"🔑 快速模型 API Key: {'已配置' if config['quick_api_key'] else '未配置（将使用环境变量）'}")
        logger.info(f"🔑 深度模型 API Key: {'已配置' if config['deep_api_key'] else '未配置（将使用环境变量）'}")
    except Exception as e:
        logger.warning(f"⚠️  无法从数据库获取 backend_url 和 API Key: {e}")
        config["backend_url"] = _get_default_backend_url(llm_provider)

        logger.info(f"⚠️  使用回退的 backend_url: {config['backend_url']}")

    # 添加分析师配置
    config["selected_analysts"] = selected_analysts
    config["debug"] = False

    # 分析模式：light=快评(精简链), full=尽调(完整链)，兼容旧值 quick/deep
    config["mode"] = "light" if mode in ("light", "quick") else "full"

    # 🔧 添加模型配置参数（max_tokens、temperature、timeout、retry_times）
    if quick_model_config:
        config["quick_model_config"] = quick_model_config
        logger.info(f"🔧 [快速模型配置] max_tokens={quick_model_config.get('max_tokens')}, "
                   f"temperature={quick_model_config.get('temperature')}, "
                   f"timeout={quick_model_config.get('timeout')}, "
                   f"retry_times={quick_model_config.get('retry_times')}")

    if deep_model_config:
        config["deep_model_config"] = deep_model_config
        logger.info(f"🔧 [深度模型配置] max_tokens={deep_model_config.get('max_tokens')}, "
                   f"temperature={deep_model_config.get('temperature')}, "
                   f"timeout={deep_model_config.get('timeout')}, "
                   f"retry_times={deep_model_config.get('retry_times')}")

    logger.info("📋 ========== 创建分析配置完成 ==========")
    logger.info(f"   🔥 辩论轮次: {config['max_debate_rounds']}")
    logger.info(f"   ⚖️ 风险讨论轮次: {config['max_risk_discuss_rounds']}")
    logger.info(f"   🤖 LLM供应商: {llm_provider}")
    logger.info(f"   ⚡ 快速模型: {config['quick_think_llm']}")
    logger.info(f"   🧠 深度模型: {config['deep_think_llm']}")
    logger.info("📋 ========================================")

    return config


class SimpleAnalysisService:
    """简化的股票分析服务类"""

    def __init__(self):
        self._trading_graph_cache = {}
        self.memory_manager = get_memory_state_manager()

        # 进度跟踪器缓存
        self._progress_trackers: dict[str, RedisProgressTracker] = {}

        # 🔧 创建共享的线程池，支持并发执行多个分析任务
        # 默认最多同时执行3个分析任务（可根据服务器资源调整）
        import concurrent.futures
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

        logger.info(f"🔧 [服务初始化] SimpleAnalysisService 实例ID: {id(self)}")
        logger.info(f"🔧 [服务初始化] 内存管理器实例ID: {id(self.memory_manager)}")
        logger.info("🔧 [服务初始化] 线程池最大并发数: 3")

        # 设置 WebSocket 管理器
        # 简单的股票名称缓存，减少重复查询
        self._stock_name_cache: dict[str, str] = {}

        # 设置 WebSocket 管理器
        try:
            from app.services.websocket_manager import get_websocket_manager
            self.memory_manager.set_websocket_manager(get_websocket_manager())
        except ImportError:
            logger.warning("⚠️ WebSocket 管理器不可用")

    async def _update_progress_async(self, task_id: str, progress: int, message: str):
        """异步更新进度（内存和MongoDB）"""
        try:
            # 更新内存
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RUNNING,
                progress=progress,
                message=message,
                current_step=message
            )

            # 更新 MongoDB
            from datetime import datetime

            from app.core.database import get_mongo_db
            db = get_mongo_db()
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "progress": progress,
                        "current_step": message,
                        "message": message,
                        "updated_at": now_tz()
                    }
                }
            )
            logger.debug(f"✅ [异步更新] 已更新内存和MongoDB: {progress}%")
        except Exception as e:
            logger.warning(f"⚠️ [异步更新] 失败: {e}")

    async def _resolve_stock_name(self, code: str | None) -> str:
        """解析股票名称（带缓存）- 从数据库stock_basic_info表查询"""
        if not code:
            return ""
        # 命中缓存
        if code in self._stock_name_cache:
            return self._stock_name_cache[code]
        name = None
        try:
            # 从数据库 stock_basic_info 表查询股票名称
            db = get_mongo_db()
            code6 = str(code).strip().zfill(6)
            
            # 按数据源优先级查询
            source_priority = ["tushare", "multi_source", "akshare", "baostock"]
            for src in source_priority:
                b = await db["stock_basic_info"].find_one(
                    {"code": code6, "source": src},
                    {"name": 1, "_id": 0}
                )
                if b and b.get("name"):
                    name = b["name"]
                    break
            
            # 如果所有数据源都没有，尝试不带 source 条件查询（兼容旧数据）
            if not name:
                b = await db["stock_basic_info"].find_one(
                    {"code": code6},
                    {"name": 1, "_id": 0}
                )
                if b and b.get("name"):
                    name = b["name"]
        except Exception as e:
            logger.warning(f"⚠️ 获取股票名称失败: {code} - {e}")
        
        if not name:
            name = f"股票{code}"
        # 写缓存
        self._stock_name_cache[code] = name
        return name

    async def _enrich_stock_names(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """为任务列表补齐股票名称(就地更新)"""
        import re
        try:
            for t in tasks:
                code = t.get("stock_code") or t.get("stock_symbol")
                name = t.get("stock_name")
                # 如果没有名称，或者是兜底格式的名称（以"股票"开头后跟数字），则重新查询
                is_placeholder = False
                if name and isinstance(name, str) and re.match(r'^股票\d+$', name):
                    is_placeholder = True
                if (not name or is_placeholder) and code:
                    t["stock_name"] = await self._resolve_stock_name(code)
        except Exception as e:
            logger.warning(f"⚠️ 补齐股票名称时出现异常: {e}")
        return tasks

    def _convert_user_id(self, user_id: str) -> PyObjectId:
        """将字符串用户ID转换为PyObjectId"""
        try:
            logger.info(f"🔄 开始转换用户ID: {user_id} (类型: {type(user_id)})")

            # 如果是admin用户，使用固定的ObjectId
            if user_id == "admin":
                admin_object_id = ObjectId("507f1f77bcf86cd799439011")
                logger.info(f"🔄 转换admin用户ID: {user_id} -> {admin_object_id}")
                return PyObjectId(admin_object_id)
            else:
                # 尝试将字符串转换为ObjectId
                object_id = ObjectId(user_id)
                logger.info(f"🔄 转换用户ID: {user_id} -> {object_id}")
                return PyObjectId(object_id)
        except Exception as e:
            logger.error(f"❌ 用户ID转换失败: {user_id} -> {e}")
            # 如果转换失败，生成一个新的ObjectId
            new_object_id = ObjectId()
            logger.warning(f"⚠️ 生成新的用户ID: {new_object_id}")
            return PyObjectId(new_object_id)

    def _get_trading_graph(self, config: dict[str, Any], callbacks: list | None = None) -> TradingAgentsGraph:
        """获取或创建TradingAgents实例

        ⚠️ 注意：为了避免并发执行时的数据混淆，每次都创建新实例
        虽然这会增加一些初始化开销，但可以确保线程安全

        TradingAgentsGraph 实例包含可变状态（self.ticker, self.curr_state等），
        如果多个线程共享同一个实例，会导致数据混淆。
        
        Args:
            config: 配置字典
            callbacks: 可选的回调函数列表，用于接收 LangGraph 的进度更新
        """
        # 🔧 [并发安全] 每次都创建新实例，避免多线程共享状态
        # 不再使用缓存，因为 TradingAgentsGraph 有可变的实例变量
        logger.info("🔧 创建新的TradingAgents实例（并发安全模式）...")
        logger.info(f"🔍 [_get_trading_graph] config中的selected_analysts: {config.get('selected_analysts')}")

        trading_graph = TradingAgentsGraph(
            selected_analysts=config.get("selected_analysts", ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]),
            debug=config.get("debug", False),
            config=config,
            callbacks=callbacks,
            mode=config.get("mode", "full")
        )

        logger.info(f"✅ TradingAgents实例创建成功（实例ID: {id(trading_graph)}）")

        return trading_graph

    async def create_analysis_task(
        self,
        user_id: str,
        request: SingleAnalysisRequest,
        batch_id: str | None = None
    ) -> dict[str, Any]:
        """创建分析任务（立即返回，不执行分析）

        Args:
            batch_id: 可选，所属批次的 batch_id，用于批量分析归并与批次进度聚合。
        """
        try:
            # 生成任务ID
            task_id = str(uuid.uuid4())

            # 🔧 使用 get_symbol() 方法获取股票代码（兼容 symbol 和 stock_code 字段）
            stock_code = request.get_symbol()
            if not stock_code:
                raise ValueError("股票代码不能为空")

            logger.info(f"📝 创建分析任务: {task_id} - {stock_code}")
            logger.info(f"🔍 内存管理器实例ID: {id(self.memory_manager)}")

            # 在内存中创建任务状态
            task_state = await self.memory_manager.create_task(
                task_id=task_id,
                user_id=user_id,
                stock_code=stock_code,
                parameters=request.parameters.model_dump() if request.parameters else {},
                stock_name=(await self._resolve_stock_name(stock_code) if hasattr(self, '_resolve_stock_name') else None),
            )

            logger.info(f"✅ 任务状态已创建: {task_state.task_id}")

            # 立即验证任务是否可以查询到
            verify_task = await self.memory_manager.get_task(task_id)
            if verify_task:
                logger.info(f"✅ 任务创建验证成功: {verify_task.task_id}")
            else:
                logger.error(f"❌ 任务创建验证失败: 无法查询到刚创建的任务 {task_id}")

            # 补齐股票名称并写入数据库任务文档的初始记录
            code = stock_code
            name = await self._resolve_stock_name(code) if hasattr(self, '_resolve_stock_name') else f"股票{code}"

            try:
                db = get_mongo_db()
                result = await db.analysis_tasks.update_one(
                    {"task_id": task_id},
                    {"$setOnInsert": {
                        "task_id": task_id,
                        "user_id": user_id,
                        "stock_code": code,
                        "stock_symbol": code,
                        "stock_name": name,
                        "status": "pending",
                        "progress": 0,
                        "created_at": now_tz(),
                        "batch_id": batch_id,
                    }},
                    upsert=True
                )

                if result.upserted_id or result.matched_count > 0:
                    logger.info(f"✅ 任务已保存到MongoDB: {task_id}")
                else:
                    logger.warning(f"⚠️ MongoDB保存结果异常: matched={result.matched_count}, upserted={result.upserted_id}")

            except Exception as e:
                logger.error(f"❌ 创建任务时写入MongoDB失败: {e}")
                # 这里不应该忽略错误，因为没有MongoDB记录会导致状态查询失败
                # 但为了不影响任务执行，我们记录错误但继续执行
                import traceback
                logger.error(f"❌ MongoDB保存详细错误: {traceback.format_exc()}")

            return {
                "task_id": task_id,
                "status": "pending",
                "message": "任务已创建，等待执行"
            }

        except Exception as e:
            logger.error(f"❌ 创建分析任务失败: {e}")
            raise

    async def execute_analysis_background(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest
    ):
        """在后台执行分析任务"""
        # 🔧 使用 get_symbol() 方法获取股票代码（兼容 symbol 和 stock_code 字段）
        stock_code = request.get_symbol()

        # 添加最外层的异常捕获，确保所有异常都被记录
        try:
            logger.info(f"🎯🎯🎯 [ENTRY] execute_analysis_background 方法被调用: {task_id}")
            logger.info(f"🎯🎯🎯 [ENTRY] user_id={user_id}, stock_code={stock_code}")
        except Exception as entry_error:
            print(f"❌❌❌ [CRITICAL] 日志记录失败: {entry_error}")
            import traceback
            traceback.print_exc()

        progress_tracker = None
        try:
            logger.info(f"🚀 开始后台执行分析任务: {task_id}")

            # 🔍 验证股票代码是否存在
            logger.info(f"🔍 开始验证股票代码: {stock_code}")
            from datetime import datetime

            from tradingagents.utils.stock_validator import prepare_stock_data_async

            # 获取市场类型
            market_type = request.parameters.market_type if request.parameters else "A股"

            # 获取分析日期并转换为字符串格式
            analysis_date = request.parameters.analysis_date if request.parameters else None
            if analysis_date:
                # 如果是 datetime 对象，转换为字符串
                if isinstance(analysis_date, datetime):
                    analysis_date = analysis_date.strftime('%Y-%m-%d')
                # 如果是字符串，确保格式正确
                elif isinstance(analysis_date, str):
                    # 尝试解析并重新格式化，确保格式统一
                    try:
                        parsed_date = datetime.strptime(analysis_date, '%Y-%m-%d')
                        analysis_date = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        # 如果格式不对，使用今天
                        analysis_date = now_tz().strftime('%Y-%m-%d')
                        logger.warning(f"⚠️ 分析日期格式不正确，使用今天: {analysis_date}")

            # 🔥 使用异步版本，直接 await，避免事件循环冲突
            validation_result = await prepare_stock_data_async(
                stock_code=stock_code,
                market_type=market_type,
                period_days=30,
                analysis_date=analysis_date
            )

            if not validation_result.get("success", False):
                error_msg = f"❌ 股票代码验证失败: {validation_result.get('error', '未知错误')}"
                logger.error(error_msg)
                logger.error(f"💡 建议: {validation_result.get('warning', '请检查股票代码是否正确')}")

                # 构建用户友好的错误消息
                user_friendly_error = (
                    f"❌ 股票代码无效\n\n"
                    f"{validation_result.get('error', '未知错误')}\n\n"
                    f"💡 {validation_result.get('warning', '请检查股票代码是否正确')}"
                )

                # 更新任务状态为失败
                await self.memory_manager.update_task_status(
                    task_id=task_id,
                    status=AnalysisStatus.FAILED,
                    progress=0,
                    error_message=user_friendly_error
                )

                # 更新MongoDB状态
                await self._update_task_status(
                    task_id,
                    AnalysisStatus.FAILED,
                    0,
                    error_message=user_friendly_error
                )

                return

            logger.info(f"✅ 股票代码验证通过: {stock_code} - {validation_result.get('stock_name', '')}")
            logger.info(f"📊 市场类型: {validation_result.get('market_type', 'unknown')}")
            logger.info(f"📈 数据信息: {validation_result.get('data', {})}")

            # 在线程池中创建Redis进度跟踪器（避免阻塞事件循环）
            def create_progress_tracker():
                """在线程中创建进度跟踪器"""
                logger.info(f"📊 [线程] 创建进度跟踪器: {task_id}")
                tracker = RedisProgressTracker(
                    task_id=task_id,
                    analysts=(request.parameters.selected_analysts if request.parameters else None) or ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"],
                    llm_provider="dashscope"
                )
                logger.info(f"✅ [线程] 进度跟踪器创建完成: {task_id}")
                return tracker

            progress_tracker = await asyncio.to_thread(create_progress_tracker)

            # 缓存进度跟踪器
            self._progress_trackers[task_id] = progress_tracker

            # 注册到日志监控
            register_analysis_tracker(task_id, progress_tracker)

            # 初始化进度（在线程中执行）
            await asyncio.to_thread(
                progress_tracker.update_progress,
                {
                    "progress_percentage": 10,
                    "last_message": "🚀 开始股票分析"
                }
            )

            # 更新状态为运行中
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RUNNING,
                progress=10,
                message="分析开始...",
                current_step="initialization"
            )

            # 同步更新MongoDB状态
            await self._update_task_status(task_id, AnalysisStatus.PROCESSING, 10)

            # 数据准备阶段（在线程中执行）
            await asyncio.to_thread(
                progress_tracker.update_progress,
                {
                    "progress_percentage": 20,
                    "last_message": "🔧 检查环境配置"
                }
            )
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RUNNING,
                progress=20,
                message="准备分析数据...",
                current_step="data_preparation"
            )

            # 同步更新MongoDB状态
            await self._update_task_status(task_id, AnalysisStatus.PROCESSING, 20)

            # 执行实际的分析
            result = await self._execute_analysis_sync(task_id, user_id, request, progress_tracker)

            # 标记进度跟踪器完成（在线程中执行）
            await asyncio.to_thread(progress_tracker.mark_completed)

            # 保存分析结果到文件和数据库
            try:
                logger.info(f"💾 开始保存分析结果: {task_id}")
                await self._save_analysis_results_complete(task_id, result)
                logger.info(f"✅ 分析结果保存完成: {task_id}")
            except Exception as save_error:
                logger.error(f"❌ 保存分析结果失败: {task_id} - {save_error}")
                # 保存失败不影响分析完成状态

            # 🔍 调试：检查即将保存到内存的result
            logger.info(f"🔍 [DEBUG] 即将保存到内存的result键: {list(result.keys())}")
            logger.info(f"🔍 [DEBUG] 即将保存到内存的decision: {bool(result.get('decision'))}")
            if result.get('decision'):
                logger.info(f"🔍 [DEBUG] 即将保存的decision内容: {result['decision']}")

            # 更新状态为完成
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="分析完成",
                current_step="completed",
                result_data=result
            )

            # 同步更新MongoDB状态为完成
            await self._update_task_status(task_id, AnalysisStatus.COMPLETED, 100)

            # 创建通知：分析完成（方案B：REST+SSE）
            try:
                from app.services.notifications_service import get_notifications_service
                svc = get_notifications_service()
                summary = str(result.get("summary", ""))[:120]
                await svc.create_and_publish(
                    payload=NotificationCreate(
                        user_id=str(user_id),
                        type='analysis',
                        title=f"{request.stock_code} 分析完成",
                        content=summary,
                        link=f"/stocks/{request.stock_code}",
                        source='analysis'
                    )
                )
            except Exception as notif_err:
                logger.warning(f"⚠️ 创建通知失败(忽略): {notif_err}")

            # 记录 token 使用
            try:
                from app.models.config import UsageRecord
                from app.services.usage_statistics_service import UsageStatisticsService

                tokens_used = result.get("tokens_used", 0) if isinstance(result, dict) else 0
                input_tokens = tokens_used // 2 if tokens_used > 0 else 2000
                output_tokens = tokens_used - input_tokens if tokens_used > 0 else 1000

                # 获取模型信息
                model_info = result.get("model_info", "Unknown") if isinstance(result, dict) else "Unknown"
                if model_info == "Unknown":
                    model_info = request.parameters.quick_analysis_model if request.parameters else "qwen-plus"

                # 估算成本（简化处理）
                cost = 0.0
                currency = "CNY"

                usage_record = UsageRecord(
                    timestamp=now_tz().isoformat(),
                    provider="dashscope",
                    model_name=model_info,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    currency=currency,
                    session_id=task_id,
                    analysis_type="stock_analysis",
                    stock_code=request.stock_code
                )

                usage_svc = UsageStatisticsService()
                success = await usage_svc.add_usage_record(usage_record)
                if success:
                    logger.info(f"💰 记录使用成本: {model_info} - task={task_id}")
                else:
                    logger.warning(f"⚠️ 记录使用成本失败: task={task_id}")
            except Exception as usage_err:
                logger.error(f"❌ 记录 token 使用失败: {usage_err}")

            logger.info(f"✅ 后台分析任务完成: {task_id}")

        except Exception as e:
            logger.error(f"❌ 后台分析任务失败: {task_id} - {e}")

            # 格式化错误信息为用户友好的提示
            from ..utils.error_formatter import ErrorFormatter

            # 收集上下文信息
            error_context = {}
            if hasattr(request, 'parameters') and request.parameters:
                if hasattr(request.parameters, 'quick_model'):
                    error_context['model'] = request.parameters.quick_model
                if hasattr(request.parameters, 'deep_model'):
                    error_context['model'] = request.parameters.deep_model

            # 格式化错误
            formatted_error = ErrorFormatter.format_error(str(e), error_context)

            # 构建用户友好的错误消息
            user_friendly_error = (
                f"{formatted_error['title']}\n\n"
                f"{formatted_error['message']}\n\n"
                f"💡 {formatted_error['suggestion']}"
            )

            # 标记进度跟踪器失败
            if progress_tracker:
                progress_tracker.mark_failed(user_friendly_error)

            # 更新状态为失败
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                progress=0,
                message="分析失败",
                current_step="failed",
                error_message=user_friendly_error
            )

            # 同步更新MongoDB状态为失败
            await self._update_task_status(task_id, AnalysisStatus.FAILED, 0, user_friendly_error)
        finally:
            # 清理进度跟踪器缓存
            if task_id in self._progress_trackers:
                del self._progress_trackers[task_id]

            # 从日志监控中注销
            unregister_analysis_tracker(task_id)

    async def _execute_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: RedisProgressTracker | None = None
    ) -> dict[str, Any]:
        """同步执行分析（在共享线程池中运行）"""
        # 🔧 使用共享线程池，支持多个任务并发执行
        # 不再每次创建新的线程池，避免串行执行
        loop = asyncio.get_event_loop()
        logger.info(f"🚀 [线程池] 提交分析任务到共享线程池: {task_id} - {request.stock_code}")
        result = await loop.run_in_executor(
            self._thread_pool,  # 使用共享线程池
            self._run_analysis_sync,
            task_id,
            user_id,
            request,
            progress_tracker
        )
        logger.info(f"✅ [线程池] 分析任务执行完成: {task_id}")
        return result

    def _run_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: RedisProgressTracker | None = None
    ) -> dict[str, Any]:
        """同步执行分析的具体实现"""
        try:
            # 在线程中重新初始化日志系统
            from tradingagents.utils.logging_init import get_logger, init_logging
            init_logging()
            thread_logger = get_logger('analysis_thread')

            thread_logger.info(f"🔄 [线程池] 开始执行分析: {task_id} - {request.stock_code}")
            logger.info(f"🔄 [线程池] 开始执行分析: {task_id} - {request.stock_code}")

            # 🔧 根据 RedisProgressTracker 的步骤权重计算准确的进度
            # 基础准备阶段 (10%): 0.03 + 0.02 + 0.01 + 0.02 + 0.02 = 0.10
            # 步骤索引 0-4 对应 0-10%

            # 异步更新进度（在线程池中调用）
            def update_progress_sync(progress: int, message: str, step: str):
                """在线程池中同步更新进度（统一刻度，只前进不回退）"""
                try:
                    # 计算有效进度：不得超过当前进度，保证各通道（Redis/内存/MongoDB）刻度一致
                    current_pct = progress_tracker.progress_data.get('progress_percentage', 0) if progress_tracker else progress
                    effective = progress if progress > current_pct else int(current_pct)

                    # 同时更新 Redis 进度跟踪器
                    if progress_tracker:
                        progress_tracker.update_progress({
                            "progress_percentage": progress,
                            "last_message": message
                        })

                    # 🔥 使用同步方式更新内存和 MongoDB，避免事件循环冲突
                    # 1. 更新内存中的任务状态（使用新事件循环）
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(
                            self.memory_manager.update_task_status(
                                task_id=task_id,
                                status=TaskStatus.RUNNING,
                                progress=effective,
                                message=message,
                                current_step=step
                            )
                        )
                    finally:
                        loop.close()

                    # 2. 更新 MongoDB（使用同步客户端，避免事件循环冲突）
                    from datetime import datetime

                    from pymongo import MongoClient

                    from app.core.config import settings

                    sync_client = MongoClient(settings.MONGO_URI)
                    sync_db = sync_client[settings.MONGO_DB]

                    sync_db.analysis_tasks.update_one(
                        {"task_id": task_id},
                        {
                            "$set": {
                                "progress": effective,
                                "current_step": step,
                                "message": message,
                                "updated_at": now_tz()
                            }
                        }
                    )
                    sync_client.close()

                except Exception as e:
                    logger.warning(f"⚠️ 进度更新失败: {e}")

            # 配置阶段 - 对应步骤3 "⚙️ 参数设置" (6-8%)
            update_progress_sync(7, "⚙️ 配置分析参数", "configuration")

            # 🆕 智能模型选择逻辑
            from app.services.model_capability_service import get_model_capability_service
            capability_service = get_model_capability_service()

            # 1. 检查前端是否指定了模型
            if (request.parameters and
                hasattr(request.parameters, 'quick_analysis_model') and
                hasattr(request.parameters, 'deep_analysis_model') and
                request.parameters.quick_analysis_model and
                request.parameters.deep_analysis_model):

                # 使用前端指定的模型
                quick_model = request.parameters.quick_analysis_model
                deep_model = request.parameters.deep_analysis_model

                logger.info(f"📝 [分析服务] 用户指定模型: quick={quick_model}, deep={deep_model}")
            else:
                # 2. 自动推荐默认模型
                quick_model, deep_model = capability_service.recommend_default_models()
                logger.info(f"🤖 自动推荐模型: quick={quick_model}, deep={deep_model}")

            # 🔧 根据快速模型和深度模型分别查找对应的供应商和 API URL
            quick_provider_info = get_provider_and_url_by_model_sync(quick_model)
            deep_provider_info = get_provider_and_url_by_model_sync(deep_model)

            quick_provider = quick_provider_info["provider"]
            deep_provider = deep_provider_info["provider"]
            quick_backend_url = quick_provider_info["backend_url"]
            deep_backend_url = deep_provider_info["backend_url"]

            logger.info(f"🔍 [供应商查找] 快速模型 {quick_model} 对应的供应商: {quick_provider}")
            logger.info(f"🔍 [API地址] 快速模型使用 backend_url: {quick_backend_url}")
            logger.info(f"🔍 [供应商查找] 深度模型 {deep_model} 对应的供应商: {deep_provider}")
            logger.info(f"🔍 [API地址] 深度模型使用 backend_url: {deep_backend_url}")

            # 检查两个模型是否来自同一个厂家
            if quick_provider == deep_provider:
                logger.info(f"✅ [供应商验证] 两个模型来自同一厂家: {quick_provider}")
            else:
                logger.info(f"✅ [混合模式] 快速模型({quick_provider}) 和 深度模型({deep_provider}) 来自不同厂家")

            # 获取市场类型
            market_type = request.parameters.market_type if request.parameters else "A股"
            logger.info(f"📊 [市场类型] 使用市场类型: {market_type}")

            # 🧹 [过滤] 只保留 setup.py 支持的 7 种分析师
            # 支持的: market, social, news, fundamentals, policy, hot_money, lockup
            supported_analysts = {"market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"}
            raw_analysts = request.parameters.selected_analysts if request.parameters else ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]

            # 中文名到英文 key 的映射（兼容前端发送中文的情况）
            cn_to_en = {
                "市场分析师": "market",
                "技术分析师": "market",
                "社交媒体分析师": "social",
                "情绪分析师": "social",
                "新闻分析师": "news",
                "基本面分析师": "fundamentals",
                "政策分析师": "policy",
                "游资追踪师": "hot_money",
                "资金追踪师": "hot_money",
                "解禁追踪师": "lockup",
                "限售解禁师": "lockup",
            }

            filtered_analysts = []
            for a in raw_analysts:
                # 已经是英文 key
                if a in supported_analysts:
                    if a not in filtered_analysts:
                        filtered_analysts.append(a)
                # 中文名称，尝试映射
                elif a in cn_to_en:
                    en_key = cn_to_en[a]
                    if en_key not in filtered_analysts:
                        filtered_analysts.append(en_key)
                else:
                    logger.warning(f"⚠️  跳过不支持的分析师: {a}")

            # 🔧 强制使用全部7个分析师（用户需求：7个分析师是都要选择的）
            # 无论前端传什么，都确保包含全部7个分析师
            all_analysts = ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]
            for analyst in all_analysts:
                if analyst not in filtered_analysts:
                    filtered_analysts.append(analyst)
                    logger.info(f"📊 [分析师] 补全缺失的分析师: {analyst}")

            logger.info(f"📊 [分析师] 原始: {raw_analysts}")
            logger.info(f"📊 [分析师] 过滤后: {filtered_analysts}")

            # 读取分析模式（light=快评精简链, full=尽调完整链），兼容旧值 quick/deep
            req_mode = (request.parameters.mode if request.parameters else "") or "full"

            # 创建分析配置（支持混合模式）
            config = create_analysis_config(
                selected_analysts=filtered_analysts,
                quick_model=quick_model,
                deep_model=deep_model,
                llm_provider=quick_provider,  # 主要使用快速模型的供应商
                market_type=market_type,  # 使用前端传递的市场类型
                mode=req_mode
            )

            logger.info(f"🎯 [分析模式] 页面选择: '{req_mode}' -> 实际执行链路: '{config['mode']}'")

            # 🔧 添加混合模式配置
            config["quick_provider"] = quick_provider
            config["deep_provider"] = deep_provider
            config["quick_backend_url"] = quick_backend_url
            config["deep_backend_url"] = deep_backend_url
            config["backend_url"] = quick_backend_url  # 保持向后兼容

            # 🔍 验证配置中的模型
            logger.info(f"🔍 [模型验证] 配置中的快速模型: {config.get('quick_think_llm')}")
            logger.info(f"🔍 [模型验证] 配置中的深度模型: {config.get('deep_think_llm')}")
            logger.info(f"🔍 [模型验证] 配置中的LLM供应商: {config.get('llm_provider')}")

            # 定义进度回调函数，用于接收 LangGraph 的实时进度
            # 统一刻度：节点进度映射表（整数百分比，与 RedisProgressTracker 的累计步骤权重对应）
            # 必须与 trading_graph._send_progress_update 发出的标签逐字一致，且只增不减
            node_progress_map = {
                # 分析师阶段 (预置 20% -> 45%) - 7个分析师，每个 +5%
                "📊 市场分析师": 25,        # 20% + 5%
                "💬 社交媒体分析师": 30,    # 25% + 5%
                "📰 新闻分析师": 35,        # 30% + 5%
                "💼 基本面分析师": 40,      # 35% + 5%
                "📜 政策分析师": 45,        # 40% + 5%
                "💰 游资追踪师": 50,        # 45% + 5%
                "🔓 解禁追踪师": 55,        # 50% + 5%
                # 数据质量审核 (55% -> 65%)
                "✅ 数据质量审核": 62,       # 55% + 7%
                # 研究辩论阶段 (65% -> 78%)
                "🐂 看涨研究员": 68,        # 62% + 6%
                "🐻 看跌研究员": 73,        # 68% + 5%
                "👔 研究经理": 78,          # 73% + 5%
                # 交易员阶段 (78% -> 84%)
                "💼 交易员决策": 84,         # 78% + 6%
                # 风险评估阶段 (84% -> 95%)
                "🔥 激进风险评估": 88,       # 84% + 4%
                "🛡️ 保守风险评估": 91,       # 88% + 3%
                "⚖️ 中性风险评估": 93,       # 91% + 2%
                "🎯 投资组合经理": 95,       # 93% + 2%
                # 最终阶段 (95% -> 97%，最终 100% 由 mark_completed 完成)
                "📡 最终决策": 97,           # 95% + 2%
            }

            def graph_progress_callback(message: str):
                """接收 LangGraph 的进度更新

                根据节点名称直接映射到进度百分比，确保与 RedisProgressTracker 的步骤权重一致
                注意：只在进度增加时更新，避免覆盖 RedisProgressTracker 的虚拟步骤进度
                """
                try:
                    logger.info(f"🎯🎯🎯 [Graph进度回调被调用] message={message}")
                    # 动态从缓存中获取 progress_tracker
                    progress_tracker_local = self._progress_trackers.get(task_id)
                    if not progress_tracker_local:
                        logger.warning("⚠️ progress_tracker 为 None，无法更新进度")
                        return

                    # 查找节点对应的进度百分比
                    progress_pct = node_progress_map.get(message)

                    if progress_pct is not None:
                        # 获取当前进度（使用 progress_data 属性）
                        current_progress = progress_tracker_local.progress_data.get('progress_percentage', 0)

                        # 只在进度增加时更新，避免覆盖虚拟步骤的进度
                        if int(progress_pct) > current_progress:
                            # 更新 Redis 进度跟踪器
                            progress_tracker_local.update_progress({
                                'progress_percentage': int(progress_pct),
                                'last_message': message
                            })
                            logger.info(f"📊 [Graph进度] 进度已更新: {current_progress}% → {int(progress_pct)}% - {message}")

                            # 🔥 同时更新内存和 MongoDB
                            try:
                                import asyncio
                                from datetime import datetime

                                # 尝试获取当前运行的事件循环
                                try:
                                    loop = asyncio.get_running_loop()
                                    # 如果在事件循环中，使用 create_task
                                    asyncio.create_task(
                                        self._update_progress_async(task_id, int(progress_pct), message)
                                    )
                                    logger.debug(f"✅ [Graph进度] 已提交异步更新任务: {int(progress_pct)}%")
                                except RuntimeError:
                                    # 没有运行的事件循环，使用同步方式更新 MongoDB
                                    from pymongo import MongoClient

                                    from app.core.config import settings

                                    # 创建同步 MongoDB 客户端
                                    sync_client = MongoClient(settings.MONGO_URI)
                                    sync_db = sync_client[settings.MONGO_DB]

                                    # 同步更新 MongoDB
                                    sync_db.analysis_tasks.update_one(
                                        {"task_id": task_id},
                                        {
                                            "$set": {
                                                "progress": int(progress_pct),
                                                "current_step": message,
                                                "message": message,
                                                "updated_at": now_tz()
                                            }
                                        }
                                    )
                                    sync_client.close()

                                    # 异步更新内存（创建新的事件循环）
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        loop.run_until_complete(
                                            self.memory_manager.update_task_status(
                                                task_id=task_id,
                                                status=TaskStatus.RUNNING,
                                                progress=int(progress_pct),
                                                message=message,
                                                current_step=message
                                            )
                                        )
                                    finally:
                                        loop.close()

                                    logger.debug(f"✅ [Graph进度] 已同步更新内存和MongoDB: {int(progress_pct)}%")
                            except Exception as sync_err:
                                logger.warning(f"⚠️ [Graph进度] 同步更新失败: {sync_err}")
                        else:
                            # 进度没有增加，只更新消息
                            progress_tracker_local.update_progress({
                                'last_message': message
                            })
                            logger.info(f"📊 [Graph进度] 进度未变化({current_progress}% >= {int(progress_pct)}%)，仅更新消息: {message}")
                    else:
                        # 未知节点，只更新消息
                        logger.warning(f"⚠️ [Graph进度] 未知节点: {message}，仅更新消息")
                        progress_tracker_local.update_progress({
                            'last_message': message
                        })

                except Exception as e:
                    logger.error(f"❌ Graph进度回调失败: {e}", exc_info=True)

            # 初始化分析引擎 - 对应步骤4 "🚀 启动引擎" (8-10%)
            update_progress_sync(9, "🚀 初始化AI分析引擎", "engine_initialization")
            trading_graph = self._get_trading_graph(config, callbacks=[graph_progress_callback])

            # 🔍 验证TradingGraph实例中的配置
            logger.info(f"🔍 [引擎验证] TradingGraph配置中的快速模型: {trading_graph.config.get('quick_think_llm')}")
            logger.info(f"🔍 [引擎验证] TradingGraph配置中的深度模型: {trading_graph.config.get('deep_think_llm')}")

            # 准备分析数据
            start_time = now_tz()

            # 🔧 使用前端传递的分析日期，如果没有则使用当前日期
            if request.parameters and hasattr(request.parameters, 'analysis_date') and request.parameters.analysis_date:
                # 前端传递的是 datetime 对象或字符串
                if isinstance(request.parameters.analysis_date, datetime):
                    analysis_date = request.parameters.analysis_date.strftime("%Y-%m-%d")
                elif isinstance(request.parameters.analysis_date, str):
                    analysis_date = request.parameters.analysis_date
                else:
                    analysis_date = now_tz().strftime("%Y-%m-%d")
                logger.info(f"📅 使用前端指定的分析日期: {analysis_date}")
            else:
                analysis_date = now_tz().strftime("%Y-%m-%d")
                logger.info(f"📅 使用当前日期作为分析日期: {analysis_date}")

            # 🔧 智能日期范围处理：获取最近10天的数据，自动处理周末/节假日
            # 这样可以确保即使是周末或节假日，也能获取到最后一个交易日的数据
            from tradingagents.utils.dataflow_utils import get_trading_date_range
            data_start_date, data_end_date = get_trading_date_range(analysis_date, lookback_days=10)

            logger.info(f"📅 分析目标日期: {analysis_date}")
            logger.info(f"📅 数据查询范围: {data_start_date} 至 {data_end_date} (最近10天)")
            logger.info("💡 说明: 获取10天数据可自动处理周末、节假日和数据延迟问题")

            # 开始分析 - 进度10%，即将进入分析师阶段
            # 注意：不要手动设置过高的进度，让 graph_progress_callback 来更新实际的分析进度
            # 统一刻度：不再使用模拟进度线程（simulate_progress），避免假进度抢占真实进度
            update_progress_sync(10, "🤖 开始多智能体协作分析", "agent_analysis")

            logger.info("🚀 准备调用 trading_graph.propagate（适配新接口，不再传 progress_callback）")

            # 执行实际分析 - 新接口 propagate(company_name, trade_date)
            # 进度回调通过 LangChain callbacks 注入到 TradingAgentsGraph.__init__ 中
            state, decision = trading_graph.propagate(
                request.stock_code,
                analysis_date,
            )

            logger.info("✅ trading_graph.propagate 执行完成")

            # 🔍 调试：检查decision的结构
            logger.info(f"🔍 [DEBUG] Decision类型: {type(decision)}")
            logger.info(f"🔍 [DEBUG] Decision内容: {decision}")
            if isinstance(decision, dict):
                logger.info(f"🔍 [DEBUG] Decision键: {list(decision.keys())}")
            elif hasattr(decision, '__dict__'):
                logger.info(f"🔍 [DEBUG] Decision属性: {list(vars(decision).keys())}")

            # 处理结果
            if progress_tracker:
                progress_tracker.update_progress("📊 处理分析结果")
            update_progress_sync(90, "处理分析结果...", "result_processing")

            execution_time = (now_tz() - start_time).total_seconds()

            # 从state中提取reports字段
            reports = {}
            try:
                # 定义所有可能的报告字段
                report_fields = [
                    'market_report',
                    'sentiment_report',
                    'news_report',
                    'fundamentals_report',
                    'policy_report',
                    'hot_money_report',
                    'lockup_report',
                    'investment_plan',
                    'trader_investment_plan',
                    'risk_control_decision',
                    'final_trade_decision'
                ]

                # 从state中提取报告内容
                for field in report_fields:
                    if hasattr(state, field):
                        value = getattr(state, field, "")
                    elif isinstance(state, dict) and field in state:
                        value = state[field]
                    else:
                        value = ""

                    if isinstance(value, str) and value.strip():  # 保存所有非空报告，包括失败/占位信息
                        reports[field] = value.strip()
                        logger.info(f"📊 [REPORTS] 提取报告: {field} - 长度: {len(value.strip())}")
                    else:
                        logger.debug(f"⚠️ [REPORTS] 跳过报告: {field} - 内容为空")

                # 处理研究团队辩论状态报告
                if hasattr(state, 'investment_debate_state') or (isinstance(state, dict) and 'investment_debate_state' in state):
                    debate_state = getattr(state, 'investment_debate_state', None) if hasattr(state, 'investment_debate_state') else state.get('investment_debate_state')
                    if debate_state:
                        # 提取多头研究员历史
                        if hasattr(debate_state, 'bull_history'):
                            bull_content = getattr(debate_state, 'bull_history', "")
                        elif isinstance(debate_state, dict) and 'bull_history' in debate_state:
                            bull_content = debate_state['bull_history']
                        else:
                            bull_content = ""

                        if bull_content and len(bull_content.strip()) > 10:
                            reports['bull_researcher'] = bull_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: bull_researcher - 长度: {len(bull_content.strip())}")

                        # 提取空头研究员历史
                        if hasattr(debate_state, 'bear_history'):
                            bear_content = getattr(debate_state, 'bear_history', "")
                        elif isinstance(debate_state, dict) and 'bear_history' in debate_state:
                            bear_content = debate_state['bear_history']
                        else:
                            bear_content = ""

                        if bear_content and len(bear_content.strip()) > 10:
                            reports['bear_researcher'] = bear_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: bear_researcher - 长度: {len(bear_content.strip())}")

                        # 提取研究经理决策
                        if hasattr(debate_state, 'judge_decision'):
                            decision_content = getattr(debate_state, 'judge_decision', "")
                        elif isinstance(debate_state, dict) and 'judge_decision' in debate_state:
                            decision_content = debate_state['judge_decision']
                        else:
                            decision_content = str(debate_state)

                        if decision_content and len(decision_content.strip()) > 10:
                            reports['research_team_decision'] = decision_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: research_team_decision - 长度: {len(decision_content.strip())}")

                # 处理风险管理团队辩论状态报告
                if hasattr(state, 'risk_debate_state') or (isinstance(state, dict) and 'risk_debate_state' in state):
                    risk_state = getattr(state, 'risk_debate_state', None) if hasattr(state, 'risk_debate_state') else state.get('risk_debate_state')
                    if risk_state:
                        # 提取激进分析师历史（兼容两种字段名：aggressive_history / risky_history）
                        risky_content = ""
                        if hasattr(risk_state, 'aggressive_history'):
                            risky_content = getattr(risk_state, 'aggressive_history', "")
                        elif isinstance(risk_state, dict) and 'aggressive_history' in risk_state:
                            risky_content = risk_state['aggressive_history']
                        elif hasattr(risk_state, 'risky_history'):
                            risky_content = getattr(risk_state, 'risky_history', "")
                        elif isinstance(risk_state, dict) and 'risky_history' in risk_state:
                            risky_content = risk_state['risky_history']

                        if risky_content and len(risky_content.strip()) > 10:
                            reports['risky_analyst'] = risky_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: risky_analyst - 长度: {len(risky_content.strip())}")

                        # 提取保守分析师历史（兼容两种字段名：conservative_history / safe_history）
                        safe_content = ""
                        if hasattr(risk_state, 'conservative_history'):
                            safe_content = getattr(risk_state, 'conservative_history', "")
                        elif isinstance(risk_state, dict) and 'conservative_history' in risk_state:
                            safe_content = risk_state['conservative_history']
                        elif hasattr(risk_state, 'safe_history'):
                            safe_content = getattr(risk_state, 'safe_history', "")
                        elif isinstance(risk_state, dict) and 'safe_history' in risk_state:
                            safe_content = risk_state['safe_history']

                        if safe_content and len(safe_content.strip()) > 10:
                            reports['safe_analyst'] = safe_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: safe_analyst - 长度: {len(safe_content.strip())}")

                        # 提取中性分析师历史
                        if hasattr(risk_state, 'neutral_history'):
                            neutral_content = getattr(risk_state, 'neutral_history', "")
                        elif isinstance(risk_state, dict) and 'neutral_history' in risk_state:
                            neutral_content = risk_state['neutral_history']
                        else:
                            neutral_content = ""

                        if neutral_content and len(neutral_content.strip()) > 10:
                            reports['neutral_analyst'] = neutral_content.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: neutral_analyst - 长度: {len(neutral_content.strip())}")

                        # 提取投资组合经理决策
                        if hasattr(risk_state, 'judge_decision'):
                            risk_decision = getattr(risk_state, 'judge_decision', "")
                        elif isinstance(risk_state, dict) and 'judge_decision' in risk_state:
                            risk_decision = risk_state['judge_decision']
                        else:
                            risk_decision = str(risk_state)

                        if risk_decision and len(risk_decision.strip()) > 10:
                            reports['risk_management_decision'] = risk_decision.strip()
                            logger.info(f"📊 [REPORTS] 提取报告: risk_management_decision - 长度: {len(risk_decision.strip())}")

                        # 提取风控约束决策（portfolio_manager生成的结构化风险约束）
                        risk_control = None
                        if hasattr(state, 'risk_control_decision'):
                            risk_control = getattr(state, 'risk_control_decision', "")
                        elif isinstance(state, dict) and 'risk_control_decision' in state:
                            risk_control = state['risk_control_decision']

                        if risk_control and len(str(risk_control).strip()) > 10:
                            reports['risk_control_decision'] = str(risk_control).strip()
                            logger.info(f"📊 [REPORTS] 提取报告: risk_control_decision - 长度: {len(str(risk_control).strip())}")

                logger.info(f"📊 [REPORTS] 从state中提取到 {len(reports)} 个报告: {list(reports.keys())}")

            except Exception as e:
                logger.warning(f"⚠️ 提取reports时出错: {e}")
                # 降级到从detailed_analysis提取
                try:
                    if isinstance(decision, dict):
                        for key, value in decision.items():
                            if isinstance(value, str) and len(value) > 50:
                                reports[key] = value
                        logger.info(f"📊 降级：从decision中提取到 {len(reports)} 个报告")
                except Exception as fallback_error:
                    logger.warning(f"⚠️ 降级提取也失败: {fallback_error}")

            # 🔥 格式化decision数据（参考web目录的实现）
            # 注意：propagate返回的decision是评级字符串(如"Buy")，不是字典
            # 需要从final_trade_decision markdown中解析完整信息
            formatted_decision = {}
            try:
                # 从final_trade_decision markdown中解析信息
                final_decision_markdown = ""
                if hasattr(state, 'final_trade_decision'):
                    final_decision_markdown = getattr(state, 'final_trade_decision', "")
                elif isinstance(state, dict) and 'final_trade_decision' in state:
                    final_decision_markdown = state.get('final_trade_decision', "")

                # 解析目标价格 (Price Target)
                target_price = None
                if final_decision_markdown:
                    price_match = re.search(r'\*\*Price Target\*\*:\s*([0-9.]+)', final_decision_markdown, re.IGNORECASE)
                    if price_match:
                        try:
                            target_price = float(price_match.group(1))
                            logger.info(f"🎯 [DEBUG] 从final_trade_decision解析到目标价: {target_price}")
                        except (ValueError, TypeError):
                            target_price = None

                # 解析评级 (Rating) - 支持中英文两种格式
                action = '持有'
                if final_decision_markdown:
                    # 英文格式
                    rating_match = re.search(r'\*\*Rating\*\*:\s*(\w+)', final_decision_markdown, re.IGNORECASE)
                    if rating_match:
                        rating = rating_match.group(1).lower()
                        action_translation = {
                            'buy': '买入', 'overweight': '增持', 'hold': '持有',
                            'underweight': '减持', 'sell': '卖出'
                        }
                        action = action_translation.get(rating, '持有')
                    else:
                        # 中文格式：最终交易决策/交易方向
                        cn_rating_match = re.search(
                            r'(?:最终交易决策|交易方向)[^：]*[：:]\s*[\*]*\s*(\S+?)(?:\s*[\*]*\s*[/／]|\n|$)',
                            final_decision_markdown
                        )
                        if cn_rating_match:
                            raw_action = cn_rating_match.group(1).strip()
                            # 标准化动作映射
                            if '买入' in raw_action or '做多' in raw_action:
                                action = '买入'
                            elif '增持' in raw_action:
                                action = '增持'
                            elif '卖出' in raw_action or '做空' in raw_action or '规避' in raw_action:
                                action = '卖出'
                            elif '减持' in raw_action:
                                action = '减持'
                            elif '持有' in raw_action or '观望' in raw_action:
                                action = '持有'
                            else:
                                action = raw_action[:4] if len(raw_action) > 4 else raw_action

                # 如果final_decision_markdown为空，使用decision字符串
                if not final_decision_markdown and isinstance(decision, str):
                    action_translation = {
                        'buy': '买入', 'overweight': '增持', 'hold': '持有',
                        'underweight': '减持', 'sell': '卖出'
                    }
                    action = action_translation.get(decision.lower(), decision)

                # 解析executive_summary/决策依据作为reasoning - 支持中英文
                reasoning = '暂无分析推理'
                confidence = 0.7
                if final_decision_markdown:
                    # 英文格式
                    exec_match = re.search(r'\*\*Executive Summary\*\*:\s*([\s\S]+?)(?:\n\*\*|\Z)', final_decision_markdown, re.IGNORECASE)
                    if exec_match:
                        reasoning = exec_match.group(1).strip()[:500]
                    else:
                        # 中文格式：尝试从核心理由/决策依据/综合裁定中提取
                        cn_reason_match = re.search(
                            r'(?:核心理由|决策依据|综合裁定|我的最终裁定|核心考量)[^：]*[：:]\s*([\s\S]{20,800}?)(?:\n\s*#{1,3}\s|$)',
                            final_decision_markdown
                        )
                        if cn_reason_match:
                            raw_reason = cn_reason_match.group(1).strip()
                            # 清理markdown符号，提取纯文本
                            raw_reason = re.sub(r'[#*`>]', '', raw_reason).strip()
                            reasoning = raw_reason[:500]

                    # 解析置信度 - 支持中英文
                    conf_match = re.search(r'(?:置信度|confidence)[^：\d]*[：:]?\s*[\*]*\s*(\d{1,3})\s*(?:/100|分)?', final_decision_markdown, re.IGNORECASE)
                    if conf_match:
                        try:
                            conf_val = int(conf_match.group(1))
                            if 0 <= conf_val <= 100:
                                confidence = conf_val / 100.0
                        except (ValueError, TypeError):
                            pass

                formatted_decision = {
                    'action': action,
                    'confidence': confidence,
                    'risk_score': 0.3,  # 默认风险评分
                    'target_price': target_price,
                    'reasoning': reasoning
                }

                logger.info(f"🎯 [DEBUG] 格式化后的decision: {formatted_decision}")
            except Exception as e:
                logger.error(f"❌ 格式化decision失败: {e}")
                formatted_decision = {
                    'action': '持有',
                    'confidence': 0.5,
                    'risk_score': 0.3,
                    'target_price': None,
                    'reasoning': '暂无分析推理'
                }

            # 🔥 按照web目录的方式生成summary和recommendation
            summary = ""
            recommendation = ""

            # 1. 优先从reports中的final_trade_decision提取summary（与web目录保持一致）
            if isinstance(reports, dict) and 'final_trade_decision' in reports:
                final_decision_content = reports['final_trade_decision']
                if isinstance(final_decision_content, str) and len(final_decision_content) > 50:
                    # 提取简明摘要（解析质量评估表格，避免原始Markdown排版混乱）
                    summary = _extract_concise_summary(final_decision_content)
                    logger.info(f"📝 [SUMMARY] 从final_trade_decision提取摘要: {len(summary)}字符")

            # 2. 如果没有final_trade_decision，从state中提取
            if not summary and isinstance(state, dict):
                final_decision = state.get('final_trade_decision', '')
                if isinstance(final_decision, str) and len(final_decision) > 50:
                    summary = _extract_concise_summary(final_decision)
                    logger.info(f"📝 [SUMMARY] 从state.final_trade_decision提取摘要: {len(summary)}字符")

            # 3. 生成recommendation（从decision的reasoning）
            if isinstance(formatted_decision, dict):
                action = formatted_decision.get('action', '持有')
                target_price = formatted_decision.get('target_price')
                reasoning = formatted_decision.get('reasoning', '')

                # 生成投资建议
                recommendation = f"投资建议：{action}。"
                if target_price:
                    recommendation += f"目标价格：{target_price}元。"
                if reasoning:
                    recommendation += f"决策依据：{reasoning}"
                logger.info(f"💡 [RECOMMENDATION] 生成投资建议: {len(recommendation)}字符")

            # 4. 如果还是没有，从其他报告中提取
            if not summary and isinstance(reports, dict):
                # 尝试从其他报告中提取摘要
                for report_name, content in reports.items():
                    if isinstance(content, str) and len(content) > 100:
                        summary = _extract_concise_summary(content)
                        logger.info(f"📝 [SUMMARY] 从{report_name}提取摘要: {len(summary)}字符")
                        break

            # 5. 最后的备用方案
            if not summary:
                summary = f"对{request.stock_code}的分析已完成，请查看详细报告。"
                logger.warning("⚠️ [SUMMARY] 使用备用摘要")

            if not recommendation:
                recommendation = "请参考详细分析报告做出投资决策。"
                logger.warning("⚠️ [RECOMMENDATION] 使用备用建议")

            # 从决策中提取模型信息
            model_info = decision.get('model_info', 'Unknown') if isinstance(decision, dict) else 'Unknown'

            # 构建结果
            result = {
                "analysis_id": str(uuid.uuid4()),
                "stock_code": request.stock_code,
                "stock_symbol": request.stock_code,  # 添加stock_symbol字段以保持兼容性
                "analysis_date": analysis_date,
                "summary": summary,
                "recommendation": recommendation,
                "confidence_score": formatted_decision.get("confidence", 0.0) if isinstance(formatted_decision, dict) else 0.0,
                "risk_level": "中等",  # 可以根据risk_score计算
                "key_points": [],  # 可以从reasoning中提取关键点
                "detailed_analysis": decision,
                "execution_time": execution_time,
                "tokens_used": decision.get("tokens_used", 0) if isinstance(decision, dict) else 0,
                "state": _sanitize_state_for_mongo(state),
                # 添加分析师信息
                "analysts": request.parameters.selected_analysts if request.parameters else [],
                # 添加提取的报告内容
                "reports": reports,
                # 🔥 关键修复：添加格式化后的decision字段！
                "decision": formatted_decision,
                # 🔥 添加模型信息字段
                "model_info": model_info,
                # 🆕 性能指标数据
                "performance_metrics": state.get("performance_metrics", {}) if isinstance(state, dict) else {}
            }

            logger.info(f"✅ [线程池] 分析完成: {task_id} - 耗时{execution_time:.2f}秒")

            # 🔍 调试：检查返回的result结构
            logger.info(f"🔍 [DEBUG] 返回result的键: {list(result.keys())}")
            logger.info(f"🔍 [DEBUG] 返回result中有decision: {bool(result.get('decision'))}")
            if result.get('decision'):
                decision = result['decision']
                logger.info(f"🔍 [DEBUG] 返回decision内容: {decision}")

            return result

        except Exception as e:
            logger.error(f"❌ [线程池] 分析执行失败: {task_id} - {e}")

            # 格式化错误信息为用户友好的提示
            from ..utils.error_formatter import ErrorFormatter

            # 收集上下文信息
            error_context = {}
            if request and hasattr(request, 'parameters') and request.parameters:
                if hasattr(request.parameters, 'quick_model'):
                    error_context['model'] = request.parameters.quick_model
                if hasattr(request.parameters, 'deep_model'):
                    error_context['model'] = request.parameters.deep_model

            # 格式化错误
            formatted_error = ErrorFormatter.format_error(str(e), error_context)

            # 构建用户友好的错误消息
            user_friendly_error = (
                f"{formatted_error['title']}\n\n"
                f"{formatted_error['message']}\n\n"
                f"💡 {formatted_error['suggestion']}"
            )

            # 抛出包含友好错误信息的异常
            raise Exception(user_friendly_error) from e

    async def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """获取任务状态"""
        logger.info(f"🔍 查询任务状态: {task_id}")
        logger.info(f"🔍 当前服务实例ID: {id(self)}")
        logger.info(f"🔍 内存管理器实例ID: {id(self.memory_manager)}")

        # 强制使用全局内存管理器实例（临时解决方案）
        global_memory_manager = get_memory_state_manager()
        logger.info(f"🔍 全局内存管理器实例ID: {id(global_memory_manager)}")

        # 获取统计信息
        stats = await global_memory_manager.get_statistics()
        logger.info(f"📊 内存中任务统计: {stats}")

        result = await global_memory_manager.get_task_dict(task_id)
        if result:
            logger.info(f"✅ 找到任务: {task_id} - 状态: {result.get('status')}")

            # 🔧 跨进程一致性修复：独立 Worker 进程在它自己的内存管理器里写最终状态，
            # backend 进程内存仍停留在创建时的 pending/processing。若内存状态非终态而
            # MongoDB 已是终态（completed/failed/cancelled），用 MongoDB 终态覆盖陈旧内存状态。
            try:
                mongo_task = await get_mongo_db()["analysis_tasks"].find_one(
                    {"task_id": task_id}, {"status": 1, "progress": 1}
                )
                mongo_status = mongo_task.get("status") if mongo_task else None
                mem_status = result.get("status")
                terminal_statuses = {"completed", "failed", "cancelled"}
                if mongo_status in terminal_statuses and (mem_status not in terminal_statuses or mem_status != mongo_status):
                    logger.info(
                        f"🔄 用 MongoDB 终态覆盖陈旧内存状态: {mem_status} -> {mongo_status} (Worker 独立进程执行)"
                    )
                    result["status"] = mongo_status
                    if mongo_status == "completed":
                        result["progress"] = mongo_task.get("progress", 100)
                        result["current_step"] = "completed"
                        result["message"] = "分析完成"
                    elif mongo_status == "failed":
                        result["progress"] = mongo_task.get("progress", 0)
                        result["current_step"] = "failed"
                        result["message"] = "分析失败"
                    else:  # cancelled
                        result["progress"] = mongo_task.get("progress", 0)
                        result["current_step"] = "cancelled"
            except Exception as mongo_sync_err:
                logger.warning(f"⚠️ MongoDB终态协调跳过(忽略): {mongo_sync_err}")

            # 🔍 调试：检查从内存获取的result_data
            result_data = result.get('result_data')
            logger.debug(f"🔍 [GET_STATUS] result_data存在: {bool(result_data)}")
            if result_data:
                logger.debug(f"🔍 [GET_STATUS] result_data键: {list(result_data.keys())}")
                logger.debug(f"🔍 [GET_STATUS] result_data中有decision: {bool(result_data.get('decision'))}")
                if result_data.get('decision'):
                    logger.debug(f"🔍 [GET_STATUS] decision内容: {result_data['decision']}")
            else:
                logger.debug("🔍 [GET_STATUS] result_data为空或不存在（任务运行中，这是正常的）")

            # 优先从Redis获取详细进度信息
            redis_progress = get_progress_by_id(task_id)
            if redis_progress:
                logger.info(f"📊 [Redis进度] 获取到详细进度: {task_id}")

                # 从 steps 数组中提取当前步骤的名称和描述
                current_step_index = redis_progress.get('current_step', 0)
                steps = redis_progress.get('steps', [])
                current_step_name = redis_progress.get('current_step_name', '')
                current_step_description = redis_progress.get('current_step_description', '')

                # 如果 Redis 中的名称/描述为空，从 steps 数组中提取
                if not current_step_name and steps and 0 <= current_step_index < len(steps):
                    current_step_info = steps[current_step_index]
                    current_step_name = current_step_info.get('name', '')
                    current_step_description = current_step_info.get('description', '')
                    logger.info(f"📋 从steps数组提取当前步骤信息: index={current_step_index}, name={current_step_name}")

                # 合并Redis进度数据
                result.update({
                    'progress': redis_progress.get('progress_percentage', result.get('progress', 0)),
                    'current_step': current_step_index,  # 使用索引而不是名称
                    'current_step_name': current_step_name,  # 步骤名称
                    'current_step_description': current_step_description,  # 步骤描述
                    'message': redis_progress.get('last_message', result.get('message', '')),
                    'elapsed_time': redis_progress.get('elapsed_time', 0),
                    'remaining_time': redis_progress.get('remaining_time', 0),
                    'estimated_total_time': redis_progress.get('estimated_total_time', result.get('estimated_duration', 300)),  # 🔧 修复：使用Redis中的预估总时长
                    'steps': steps,
                    'start_time': result.get('start_time'),  # 保持原有格式
                    'last_update': redis_progress.get('last_update', result.get('start_time'))
                })
            else:
                # 如果Redis中没有，尝试从内存中的进度跟踪器获取
                if task_id in self._progress_trackers:
                    progress_tracker = self._progress_trackers[task_id]
                    progress_data = progress_tracker.to_dict()

                    # 合并进度跟踪器的详细信息
                    result.update({
                        'progress': progress_data['progress'],
                        'current_step': progress_data['current_step'],
                        'message': progress_data['message'],
                        'elapsed_time': progress_data['elapsed_time'],
                        'remaining_time': progress_data['remaining_time'],
                        'estimated_total_time': progress_data.get('estimated_total_time', 0),
                        'steps': progress_data['steps'],
                        'start_time': progress_data['start_time'],
                        'last_update': progress_data['last_update']
                    })
                    logger.info(f"📊 合并内存进度跟踪器数据: {task_id}")
                else:
                    logger.info(f"⚠️ 未找到进度信息: {task_id}")
        else:
            logger.warning(f"❌ 未找到任务: {task_id}")

        return result

    async def list_all_tasks(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0
    ) -> dict[str, Any]:
        """获取所有任务列表（不限用户）
        - 合并内存和 MongoDB 数据
        - 按开始时间倒序排列
        - 返回包含 total、tasks、stats 的字典
        """
        try:
            task_status = None
            if status:
                try:
                    status_mapping = {
                        "processing": "running",
                        "pending": "pending",
                        "completed": "completed",
                        "failed": "failed",
                        "cancelled": "cancelled"
                    }
                    mapped_status = status_mapping.get(status, status)
                    task_status = TaskStatus(mapped_status)
                except ValueError:
                    logger.warning(f"⚠️ [Tasks] 无效的状态值: {status}")
                    task_status = None

            # 1) 从内存读取所有任务
            logger.info(f"📋 [Tasks] 准备从内存读取所有任务: status={status}, limit={limit}, offset={offset}")
            tasks_in_mem = await self.memory_manager.list_all_tasks(
                status=task_status,
                limit=10000,
                offset=0
            )
            logger.info(f"📋 [Tasks] 内存返回数量: {len(tasks_in_mem)}")

            # 2) 从 MongoDB 读取任务
            db = get_mongo_db()
            collection = db["analysis_tasks"]

            query = {}
            if task_status:
                query["status"] = task_status.value

            # 读取全部用于计算总数和统计
            cursor = collection.find(query).sort("start_time", -1)
            tasks_from_db = []
            async for doc in cursor:
                doc.pop("_id", None)
                tasks_from_db.append(doc)

            logger.info(f"📋 [Tasks] MongoDB 返回数量: {len(tasks_from_db)}")

            # 3) 合并任务（内存优先）
            task_dict = {}

            # 先添加 MongoDB 中的任务
            for task in tasks_from_db:
                task_id = task.get("task_id")
                if task_id:
                    task_dict[task_id] = task

            # 再添加内存中的任务（覆盖 MongoDB 中的同名任务）
            for task in tasks_in_mem:
                task_id = task.get("task_id")
                if task_id:
                    task_dict[task_id] = task

            # 转换为列表并按时间排序
            merged_tasks = list(task_dict.values())
            merged_tasks.sort(key=lambda x: (x.get('start_time') or x.get('started_at') or x.get('created_at') or ''), reverse=True)

            # 计算总数
            total = len(merged_tasks)

            # 分页
            results = merged_tasks[offset:offset + limit]

            # 🔥 统一时间字段为北京时间（MongoDB 读回为 naive UTC，需转 +08:00）
            for task in results:
                for time_field in ("start_time", "end_time", "created_at", "started_at", "completed_at"):
                    value = task.get(time_field)
                    if value and hasattr(value, "isoformat"):
                        task[time_field] = to_display_iso(value)
                    elif isinstance(value, str) and value and not value.endswith(('Z', '+08:00', '+00:00')):
                        if 'T' in value or ' ' in value:
                            task[time_field] = value.replace(' ', 'T') + '+08:00'

            # 为结果补齐股票名称
            results = await self._enrich_stock_names(results)

            # 计算统计数据（基于全部合并后的数据）
            completed_count = sum(1 for t in merged_tasks if t.get('status') == 'completed')
            failed_count = sum(1 for t in merged_tasks if t.get('status') == 'failed')
            unique_stocks = len(set(
                t.get('stock_code') or t.get('symbol') or t.get('stock_symbol')
                for t in merged_tasks
                if t.get('stock_code') or t.get('symbol') or t.get('stock_symbol')
            ))

            stats = {
                "total": total,
                "completed": completed_count,
                "failed": failed_count,
                "unique_stocks": unique_stocks
            }

            logger.info(f"📋 [Tasks] 合并后总数: {total}, 返回数量: {len(results)}, 统计: {stats}")
            return {
                "tasks": results,
                "total": total,
                "stats": stats
            }
        except Exception as outer_e:
            logger.error(f"❌ list_all_tasks 外层异常: {outer_e}", exc_info=True)
            return {
                "tasks": [],
                "total": 0,
                "stats": {"total": 0, "completed": 0, "failed": 0, "unique_stocks": 0}
            }

    async def list_user_tasks(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0
    ) -> dict[str, Any]:
        """获取用户任务列表
        - 对于 processing 状态：优先从内存读取（实时进度）
        - 对于 completed/failed/all 状态：合并内存和 MongoDB 数据
        - 返回包含 total、tasks、stats 的字典
        """
        try:
            task_status = None
            if status:
                try:
                    # 前端传递的是 "processing"，但 TaskStatus 使用的是 "running"
                    # 需要做映射转换
                    status_mapping = {
                        "processing": "running",  # 前端使用 processing，内存使用 running
                        "pending": "pending",
                        "completed": "completed",
                        "failed": "failed",
                        "cancelled": "cancelled"
                    }
                    mapped_status = status_mapping.get(status, status)
                    task_status = TaskStatus(mapped_status)
                except ValueError:
                    logger.warning(f"⚠️ [Tasks] 无效的状态值: {status}")
                    task_status = None

            # 1) 从内存读取任务
            logger.info(f"📋 [Tasks] 准备从内存读取任务: user_id={user_id}, status={status} (mapped to {task_status}), limit={limit}, offset={offset}")
            tasks_in_mem = await self.memory_manager.list_user_tasks(
                user_id=user_id,
                status=task_status,
                limit=10000,
                offset=0
            )
            logger.info(f"📋 [Tasks] 内存返回数量: {len(tasks_in_mem)}")

            # 2) 🔧 对于 processing/running 状态，需要合并 MongoDB 数据以获取最新进度
            # 因为 graph_progress_callback 可能直接更新了 MongoDB，而内存数据可能是旧的

            # 3) 从 MongoDB 读取历史任务（用于合并或兜底）
            logger.info("📋 [Tasks] 从 MongoDB 读取历史任务")
            mongo_tasks: list[dict[str, Any]] = []
            count = 0
            try:
                db = get_mongo_db()

                # user_id 可能是字符串或 ObjectId，做兼容
                uid_candidates: list[Any] = [user_id]

                # 特殊处理 admin 用户
                if str(user_id) == 'admin':
                    # admin 用户：添加固定的 ObjectId 和字符串形式
                    try:
                        from bson import ObjectId
                        admin_oid_str = '507f1f77bcf86cd799439011'
                        uid_candidates.append(ObjectId(admin_oid_str))
                        uid_candidates.append(admin_oid_str)  # 兼容字符串存储
                        logger.info(f"📋 [Tasks] admin用户查询，候选ID: ['admin', ObjectId('{admin_oid_str}'), '{admin_oid_str}']")
                    except Exception as e:
                        logger.warning(f"⚠️ [Tasks] admin用户ObjectId创建失败: {e}")
                else:
                    # 普通用户：尝试转换为 ObjectId
                    try:
                        from bson import ObjectId
                        uid_candidates.append(ObjectId(user_id))
                        logger.debug(f"📋 [Tasks] 用户ID已转换为ObjectId: {user_id}")
                    except Exception as conv_err:
                        logger.warning(f"⚠️ [Tasks] 用户ID转换ObjectId失败，按字符串匹配: {conv_err}")

                # 兼容 user_id 与 user 两种字段名
                base_condition = {"$in": uid_candidates}
                or_conditions: list[dict[str, Any]] = [
                    {"user_id": base_condition},
                    {"user": base_condition}
                ]
                query = {"$or": or_conditions}

                if task_status:
                    # 使用映射后的状态值（TaskStatus枚举的value）
                    query["status"] = task_status.value
                    logger.info(f"📋 [Tasks] 添加状态过滤: {task_status.value}")

                logger.info(f"📋 [Tasks] MongoDB 查询条件: {query}")
                # 读取全部用于计算总数和统计
                cursor = db.analysis_tasks.find(query).sort("created_at", -1)
                async for doc in cursor:
                    count += 1
                    # 兼容 user_id 或 user 字段
                    user_field_val = doc.get("user_id", doc.get("user"))
                    # 🔧 兼容多种股票代码字段名：symbol, stock_code, stock_symbol
                    stock_code_value = doc.get("symbol") or doc.get("stock_code") or doc.get("stock_symbol")
                    item = {
                        "task_id": doc.get("task_id"),
                        "user_id": str(user_field_val) if user_field_val is not None else None,
                        "symbol": stock_code_value,  # 🔧 添加 symbol 字段（前端优先使用）
                        "stock_code": stock_code_value,  # 🔧 兼容字段
                        "stock_symbol": stock_code_value,  # 🔧 兼容字段
                        "stock_name": doc.get("stock_name"),
                        "status": str(doc.get("status", "pending")),
                        "progress": int(doc.get("progress", 0) or 0),
                        "message": doc.get("message", ""),
                        "current_step": doc.get("current_step", ""),
                        "start_time": doc.get("started_at") or doc.get("created_at"),
                        "end_time": doc.get("completed_at"),
                        "parameters": doc.get("parameters", {}),
                        "execution_time": doc.get("execution_time"),
                        "tokens_used": doc.get("tokens_used"),
                        # 为兼容前端，这里沿用 memory_manager 的字段名
                        "result_data": doc.get("result"),
                    }
                    # 时间格式转为 ISO 字符串（统一为北京时间）
                    # 注意：MongoDB 以 UTC 存储、读回为 naive UTC，
                    # to_display_iso 会将其正确转换为北京时间（+08:00）
                    for k in ("start_time", "end_time"):
                        if item.get(k) and hasattr(item[k], "isoformat"):
                            item[k] = to_display_iso(item[k])
                    mongo_tasks.append(item)

                logger.info(f"📋 [Tasks] MongoDB 返回数量: {count}")
            except Exception as mongo_e:
                logger.error(f"❌ MongoDB 查询任务列表失败: {mongo_e}", exc_info=True)
                # MongoDB 查询失败，继续使用内存数据

            # 4) 合并内存和 MongoDB 数据，去重
            # 🔧 对于 processing/running 状态，优先使用 MongoDB 中的进度数据
            # 因为 graph_progress_callback 直接更新 MongoDB，而内存数据可能是旧的
            task_dict = {}

            # 先添加内存中的任务
            for task in tasks_in_mem:
                task_id = task.get("task_id")
                if task_id:
                    task_dict[task_id] = task

            # 再添加 MongoDB 中的任务
            # 对于 processing/running 状态，使用 MongoDB 中的进度数据（更新）
            # 对于其他状态，如果内存中已有，则跳过（内存优先）
            for task in mongo_tasks:
                task_id = task.get("task_id")
                if not task_id:
                    continue

                # 如果内存中已有这个任务
                if task_id in task_dict:
                    mem_task = task_dict[task_id]
                    mongo_task = task

                    # 如果是 processing/running 状态，使用 MongoDB 中的进度数据
                    if mongo_task.get("status") in ["processing", "running"]:
                        # 保留内存中的基本信息，但更新进度相关字段
                        mem_task["progress"] = mongo_task.get("progress", mem_task.get("progress", 0))
                        mem_task["message"] = mongo_task.get("message", mem_task.get("message", ""))
                        mem_task["current_step"] = mongo_task.get("current_step", mem_task.get("current_step", ""))
                        logger.debug(f"🔄 [Tasks] 更新任务进度: {task_id}, progress={mem_task['progress']}%")
                else:
                    # 内存中没有，直接添加 MongoDB 中的任务
                    task_dict[task_id] = task

            # 转换为列表并按时间排序
            merged_tasks = list(task_dict.values())
            merged_tasks.sort(key=lambda x: (x.get('start_time') or x.get('started_at') or x.get('created_at') or ''), reverse=True)

            # 计算总数
            total = len(merged_tasks)

            # 分页
            results = merged_tasks[offset:offset + limit]

            # 🔥 统一处理时区信息（确保所有时间字段都带北京时间 +08:00 标识）
            for task in results:
                for time_field in ("start_time", "end_time", "created_at", "started_at", "completed_at"):
                    value = task.get(time_field)
                    if value:
                        # 如果是 datetime 对象，统一转为北京时间 ISO 字符串
                        if hasattr(value, "isoformat"):
                            task[time_field] = to_display_iso(value)
                        # 如果是字符串且没有时区标识（内存任务为 naive 北京时间），补 +08:00
                        elif isinstance(value, str) and value and not value.endswith(('Z', '+08:00', '+00:00')):
                            if 'T' in value or ' ' in value:
                                task[time_field] = value.replace(' ', 'T') + '+08:00'

            # 为结果补齐股票名称
            results = await self._enrich_stock_names(results)

            # 计算统计数据（基于全部合并后的数据）
            completed_count = sum(1 for t in merged_tasks if t.get('status') == 'completed')
            failed_count = sum(1 for t in merged_tasks if t.get('status') == 'failed')
            unique_stocks = len(set(
                t.get('stock_code') or t.get('symbol') or t.get('stock_symbol')
                for t in merged_tasks
                if t.get('stock_code') or t.get('symbol') or t.get('stock_symbol')
            ))

            stats = {
                "total": total,
                "completed": completed_count,
                "failed": failed_count,
                "unique_stocks": unique_stocks
            }

            logger.info(f"📋 [Tasks] 合并后总数: {total}, 返回数量: {len(results)}, 统计: {stats}")
            return {
                "tasks": results,
                "total": total,
                "stats": stats
            }
        except Exception as outer_e:
            logger.error(f"❌ list_user_tasks 外层异常: {outer_e}", exc_info=True)
            return {
                "tasks": [],
                "total": 0,
                "stats": {"total": 0, "completed": 0, "failed": 0, "unique_stocks": 0}
            }

    async def cleanup_zombie_tasks(self, max_running_hours: int = 2) -> dict[str, Any]:
        """清理僵尸任务（长时间处于 processing/running 状态的任务）

        Args:
            max_running_hours: 最大运行时长（小时），超过此时长的任务将被标记为失败

        Returns:
            清理结果统计
        """
        try:
            # 1) 清理内存中的僵尸任务
            memory_cleaned = await self.memory_manager.cleanup_zombie_tasks(max_running_hours)

            # 2) 清理 MongoDB 中的僵尸任务
            db = get_mongo_db()
            from datetime import timedelta
            cutoff_time = now_tz() - timedelta(hours=max_running_hours)

            # 查找长时间处于 processing 状态的任务
            zombie_filter = {
                "status": {"$in": ["processing", "running", "pending"]},
                "$or": [
                    {"started_at": {"$lt": cutoff_time}},
                    {"created_at": {"$lt": cutoff_time, "started_at": None}}
                ]
            }

            # 更新为失败状态
            update_result = await db.analysis_tasks.update_many(
                zombie_filter,
                {
                    "$set": {
                        "status": "failed",
                        "last_error": f"任务超时（运行时间超过 {max_running_hours} 小时）",
                        "completed_at": now_tz(),
                        "updated_at": now_tz()
                    }
                }
            )

            mongo_cleaned = update_result.modified_count

            logger.info(f"🧹 僵尸任务清理完成: 内存={memory_cleaned}, MongoDB={mongo_cleaned}")

            return {
                "success": True,
                "memory_cleaned": memory_cleaned,
                "mongo_cleaned": mongo_cleaned,
                "total_cleaned": memory_cleaned + mongo_cleaned,
                "max_running_hours": max_running_hours
            }

        except Exception as e:
            logger.error(f"❌ 清理僵尸任务失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "memory_cleaned": 0,
                "mongo_cleaned": 0,
                "total_cleaned": 0
            }

    async def get_zombie_tasks(self, max_running_hours: int = 2) -> list[dict[str, Any]]:
        """获取僵尸任务列表（不执行清理，仅查询）

        Args:
            max_running_hours: 最大运行时长（小时）

        Returns:
            僵尸任务列表
        """
        try:
            db = get_mongo_db()
            from datetime import timedelta
            cutoff_time = now_tz() - timedelta(hours=max_running_hours)

            # 查找长时间处于 processing 状态的任务
            zombie_filter = {
                "status": {"$in": ["processing", "running", "pending"]},
                "$or": [
                    {"started_at": {"$lt": cutoff_time}},
                    {"created_at": {"$lt": cutoff_time, "started_at": None}}
                ]
            }

            cursor = db.analysis_tasks.find(zombie_filter).sort("created_at", -1)
            zombie_tasks = []

            async for doc in cursor:
                task = {
                    "task_id": doc.get("task_id"),
                    "user_id": str(doc.get("user_id", doc.get("user"))),
                    "stock_code": doc.get("stock_code"),
                    "stock_name": doc.get("stock_name"),
                    "status": doc.get("status"),
                    "created_at": to_display_iso(doc.get("created_at")),
                    "started_at": to_display_iso(doc.get("started_at")),
                    "running_hours": None
                }

                # 计算运行时长
                start_time = doc.get("started_at") or doc.get("created_at")
                if start_time:
                    running_seconds = (now_tz() - start_time).total_seconds()
                    task["running_hours"] = round(running_seconds / 3600, 2)

                zombie_tasks.append(task)

            logger.info(f"📋 查询到 {len(zombie_tasks)} 个僵尸任务")
            return zombie_tasks

        except Exception as e:
            logger.error(f"❌ 查询僵尸任务失败: {e}", exc_info=True)
            return []



    async def _update_task_status(
        self,
        task_id: str,
        status: AnalysisStatus,
        progress: int,
        error_message: str = None
    ):
        """更新任务状态"""
        try:
            db = get_mongo_db()
            update_data = {
                "status": status,
                "progress": progress,
                "updated_at": now_tz()
            }

            if status == AnalysisStatus.PROCESSING and progress == 10:
                update_data["started_at"] = now_tz()
            elif status == AnalysisStatus.COMPLETED:
                update_data["completed_at"] = now_tz()
            elif status == AnalysisStatus.FAILED:
                update_data["last_error"] = error_message
                update_data["completed_at"] = now_tz()

            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$set": update_data}
            )

            logger.debug(f"📊 任务状态已更新: {task_id} -> {status} ({progress}%)")

        except Exception as e:
            logger.error(f"❌ 更新任务状态失败: {task_id} - {e}")

    async def _save_analysis_result(self, task_id: str, result: dict[str, Any]):
        """保存分析结果（原始方法）"""
        try:
            db = get_mongo_db()
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"result": result}}
            )
            logger.debug(f"💾 分析结果已保存: {task_id}")
        except Exception as e:
            logger.error(f"❌ 保存分析结果失败: {task_id} - {e}")

    async def _save_analysis_result_web_style(self, task_id: str, result: dict[str, Any]):
        """保存分析结果 - 采用web目录的方式，保存到analysis_reports集合"""
        try:
            db = get_mongo_db()

            # 生成分析ID（与web目录保持一致）
            # 统一规范：MongoDB 内部一律按 UTC 存储（now_tz 为 tz-aware 北京时间，
            # 入库时由 pymongo 自动转为 UTC；strftime 仍取北京时间墙钟，analysis_id 不变）。
            # 之前用 now_tz()（naive 北京时间）会被 pymongo 当作 UTC 原样入库，产生 +8h 偏差。
            timestamp = now_tz()
            stock_symbol = result.get('stock_symbol') or result.get('stock_code', 'UNKNOWN')
            analysis_id = f"{stock_symbol}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            # 处理reports字段 - 从state中提取所有分析报告
            reports = {}
            if 'state' in result:
                try:
                    state = result['state']

                    # 定义所有可能的报告字段（7个分析师报告 + 其他报告）
                    report_fields = [
                        'market_report',
                        'sentiment_report',
                        'news_report',
                        'fundamentals_report',
                        'policy_report',
                        'hot_money_report',
                        'lockup_report',
                        'investment_plan',
                        'trader_investment_plan',
                        'risk_control_decision',
                        'final_trade_decision'
                    ]

                    # 从state中提取报告内容
                    for field in report_fields:
                        if hasattr(state, field):
                            value = getattr(state, field, "")
                        elif isinstance(state, dict) and field in state:
                            value = state[field]
                        else:
                            value = ""

                        if isinstance(value, str) and value.strip():  # 保存所有非空报告，包括失败/占位信息
                            reports[field] = value.strip()

                    # 处理研究团队辩论状态报告
                    if hasattr(state, 'investment_debate_state') or (isinstance(state, dict) and 'investment_debate_state' in state):
                        debate_state = getattr(state, 'investment_debate_state', None) if hasattr(state, 'investment_debate_state') else state.get('investment_debate_state')
                        if debate_state:
                            # 提取多头研究员历史
                            if hasattr(debate_state, 'bull_history'):
                                bull_content = getattr(debate_state, 'bull_history', "")
                            elif isinstance(debate_state, dict) and 'bull_history' in debate_state:
                                bull_content = debate_state['bull_history']
                            else:
                                bull_content = ""

                            if bull_content and len(bull_content.strip()) > 10:
                                reports['bull_researcher'] = bull_content.strip()

                            # 提取空头研究员历史
                            if hasattr(debate_state, 'bear_history'):
                                bear_content = getattr(debate_state, 'bear_history', "")
                            elif isinstance(debate_state, dict) and 'bear_history' in debate_state:
                                bear_content = debate_state['bear_history']
                            else:
                                bear_content = ""

                            if bear_content and len(bear_content.strip()) > 10:
                                reports['bear_researcher'] = bear_content.strip()

                            # 提取研究经理决策
                            if hasattr(debate_state, 'judge_decision'):
                                decision_content = getattr(debate_state, 'judge_decision', "")
                            elif isinstance(debate_state, dict) and 'judge_decision' in debate_state:
                                decision_content = debate_state['judge_decision']
                            else:
                                decision_content = str(debate_state)

                            if decision_content and len(decision_content.strip()) > 10:
                                reports['research_team_decision'] = decision_content.strip()

                    # 处理风险管理团队辩论状态报告
                    if hasattr(state, 'risk_debate_state') or (isinstance(state, dict) and 'risk_debate_state' in state):
                        risk_state = getattr(state, 'risk_debate_state', None) if hasattr(state, 'risk_debate_state') else state.get('risk_debate_state')
                        if risk_state:
                            # 提取激进分析师历史（兼容两种字段名：aggressive_history / risky_history）
                            risky_content = ""
                            if hasattr(risk_state, 'aggressive_history'):
                                risky_content = getattr(risk_state, 'aggressive_history', "")
                            elif isinstance(risk_state, dict) and 'aggressive_history' in risk_state:
                                risky_content = risk_state['aggressive_history']
                            elif hasattr(risk_state, 'risky_history'):
                                risky_content = getattr(risk_state, 'risky_history', "")
                            elif isinstance(risk_state, dict) and 'risky_history' in risk_state:
                                risky_content = risk_state['risky_history']

                            if risky_content and len(risky_content.strip()) > 10:
                                reports['risky_analyst'] = risky_content.strip()

                            # 提取保守分析师历史（兼容两种字段名：conservative_history / safe_history）
                            safe_content = ""
                            if hasattr(risk_state, 'conservative_history'):
                                safe_content = getattr(risk_state, 'conservative_history', "")
                            elif isinstance(risk_state, dict) and 'conservative_history' in risk_state:
                                safe_content = risk_state['conservative_history']
                            elif hasattr(risk_state, 'safe_history'):
                                safe_content = getattr(risk_state, 'safe_history', "")
                            elif isinstance(risk_state, dict) and 'safe_history' in risk_state:
                                safe_content = risk_state['safe_history']

                            if safe_content and len(safe_content.strip()) > 10:
                                reports['safe_analyst'] = safe_content.strip()

                            # 提取中性分析师历史
                            if hasattr(risk_state, 'neutral_history'):
                                neutral_content = getattr(risk_state, 'neutral_history', "")
                            elif isinstance(risk_state, dict) and 'neutral_history' in risk_state:
                                neutral_content = risk_state['neutral_history']
                            else:
                                neutral_content = ""

                            if neutral_content and len(neutral_content.strip()) > 10:
                                reports['neutral_analyst'] = neutral_content.strip()

                            # 提取投资组合经理决策
                            if hasattr(risk_state, 'judge_decision'):
                                risk_decision = getattr(risk_state, 'judge_decision', "")
                            elif isinstance(risk_state, dict) and 'judge_decision' in risk_state:
                                risk_decision = risk_state['judge_decision']
                            else:
                                risk_decision = str(risk_state)

                            if risk_decision and len(risk_decision.strip()) > 10:
                                reports['risk_management_decision'] = risk_decision.strip()

                    logger.info(f"📊 从state中提取到 {len(reports)} 个报告: {list(reports.keys())}")

                except Exception as e:
                    logger.warning(f"⚠️ 处理state中的reports时出错: {e}")
                    # 降级到从detailed_analysis提取
                    if 'detailed_analysis' in result:
                        try:
                            detailed_analysis = result['detailed_analysis']
                            if isinstance(detailed_analysis, dict):
                                for key, value in detailed_analysis.items():
                                    if isinstance(value, str) and len(value) > 50:
                                        reports[key] = value
                                logger.info(f"📊 降级：从detailed_analysis中提取到 {len(reports)} 个报告")
                        except Exception as fallback_error:
                            logger.warning(f"⚠️ 降级提取也失败: {fallback_error}")

            # 🔥 根据股票代码推断市场类型
            from tradingagents.utils.stock_utils import StockUtils
            market_info = StockUtils.get_market_info(stock_symbol)
            market_type_map = {
                "china_a": "A股",
                "hong_kong": "港股",
                "us": "美股",
                "unknown": "A股"  # 默认为A股
            }
            market_type = market_type_map.get(market_info.get("market", "unknown"), "A股")
            logger.info(f"📊 推断市场类型: {stock_symbol} -> {market_type}")

            # 🔥 获取股票名称
            stock_name = stock_symbol  # 默认使用股票代码
            try:
                if market_info.get("market") == "china_a":
                    # A股：使用统一接口获取股票信息
                    from tradingagents.dataflows.interface import get_china_stock_info_unified
                    stock_info = get_china_stock_info_unified(stock_symbol)
                    logger.debug(f"📊 获取股票信息返回: {stock_info[:200] if stock_info else 'None'}...")

                    if stock_info and "股票名称:" in stock_info:
                        stock_name = stock_info.split("股票名称:")[1].split("\n")[0].strip()
                        logger.info(f"✅ 获取A股名称: {stock_symbol} -> {stock_name}")
                    else:
                        # 降级方案：尝试直接从数据源管理器获取
                        logger.warning(f"⚠️ 无法从统一接口解析股票名称: {stock_symbol}，尝试降级方案")
                        try:
                            from tradingagents.dataflows.data_source_manager import (
                                get_china_stock_info_unified as get_info_dict,
                            )
                            info_dict = get_info_dict(stock_symbol)
                            if info_dict and info_dict.get('name'):
                                stock_name = info_dict['name']
                                logger.info(f"✅ 降级方案成功获取股票名称: {stock_symbol} -> {stock_name}")
                        except Exception as fallback_e:
                            logger.error(f"❌ 降级方案也失败: {fallback_e}")

                elif market_info.get("market") == "hong_kong":
                    # 港股：使用改进的港股工具
                    try:
                        from tradingagents.dataflows.providers.hk.improved_hk import get_hk_company_name_improved
                        stock_name = get_hk_company_name_improved(stock_symbol)
                        logger.info(f"📊 获取港股名称: {stock_symbol} -> {stock_name}")
                    except Exception:
                        clean_ticker = stock_symbol.replace('.HK', '').replace('.hk', '')
                        stock_name = f"港股{clean_ticker}"
                elif market_info.get("market") == "us":
                    # 美股：使用简单映射
                    us_stock_names = {
                        'AAPL': '苹果公司', 'TSLA': '特斯拉', 'NVDA': '英伟达',
                        'MSFT': '微软', 'GOOGL': '谷歌', 'AMZN': '亚马逊',
                        'META': 'Meta', 'NFLX': '奈飞'
                    }
                    stock_name = us_stock_names.get(stock_symbol.upper(), f"美股{stock_symbol}")
                    logger.info(f"📊 获取美股名称: {stock_symbol} -> {stock_name}")
            except Exception as e:
                logger.warning(f"⚠️ 获取股票名称失败: {stock_symbol} - {e}")
                stock_name = stock_symbol

            # 🔥 补充维度评分详情（技术面/基本面/... 各面评分 + 维度评分详情）
            # 在写入时用当前算法从 reports 现算并固化，前端详情页直接读取；
            # 避免在历史查询时逐条重算（每条约890ms，会拖慢 /tasks 等接口）。
            try:
                result["reports"] = reports
                result = recompute_confidence(result)
            except Exception as e:
                logger.warning(f"⚠️ 补充维度评分详情失败: {e}")

            # 构建文档（与web目录的MongoDBReportManager保持一致）
            document = {
                "analysis_id": analysis_id,
                "stock_symbol": stock_symbol,
                "stock_name": stock_name,  # 🔥 添加股票名称字段
                "market_type": market_type,  # 🔥 添加市场类型字段
                "model_info": result.get("model_info", "Unknown"),  # 🔥 添加模型信息字段
                "analysis_date": timestamp.strftime('%Y-%m-%d'),
                "timestamp": timestamp,
                "status": "completed",
                "source": "api",

                # 分析结果摘要
                "summary": result.get("summary", ""),
                "analysts": result.get("analysts", []),

                # 报告内容
                "reports": reports,

                # 🔥 维度评分详情（前端短线博弈/长线博弈各面分数）
                "维度评分详情": result.get("维度评分详情", []),
                "技术面评分": result.get("技术面评分"),
                "基本面评分": result.get("基本面评分"),
                "情绪面评分": result.get("情绪面评分"),
                "消息面评分": result.get("消息面评分"),
                "资金面评分": result.get("资金面评分"),
                "政策面评分": result.get("政策面评分"),
                "解禁面评分": result.get("解禁面评分"),
                "置信度详情": result.get("置信度详情", []),

                # 🔥 关键修复：添加格式化后的decision字段！
                "decision": result.get("decision", {}),

                # 元数据
                "created_at": timestamp,
                "updated_at": timestamp,

                # API特有字段
                "task_id": task_id,
                "recommendation": result.get("recommendation", ""),
                "confidence_score": result.get("confidence_score", 0.0),
                "risk_level": result.get("risk_level", "中等"),
                "key_points": result.get("key_points", []),
                "execution_time": result.get("execution_time", 0),
                "tokens_used": result.get("tokens_used", 0),

                # 🆕 性能指标数据
                "performance_metrics": result.get("performance_metrics", {})
            }

            # 保存到analysis_reports集合（与web目录保持一致）
            result_insert = await db.analysis_reports.insert_one(document)

            if result_insert.inserted_id:
                logger.info(f"✅ 分析报告已保存到MongoDB analysis_reports: {analysis_id}")

                # 同时更新analysis_tasks集合中的result字段，保持API兼容性
                await db.analysis_tasks.update_one(
                    {"task_id": task_id},
                    {"$set": {"result": {
                        "analysis_id": analysis_id,
                        "stock_symbol": stock_symbol,
                        "stock_code": result.get('stock_code', stock_symbol),
                        "analysis_date": result.get('analysis_date'),
                        "summary": result.get("summary", ""),
                        "recommendation": result.get("recommendation", ""),
                        "confidence_score": result.get("confidence_score", 0.0),
                        "risk_level": result.get("risk_level", "中等"),
                        "key_points": result.get("key_points", []),
                        "detailed_analysis": result.get("detailed_analysis", {}),
                        "execution_time": result.get("execution_time", 0),
                        "tokens_used": result.get("tokens_used", 0),
                        "reports": reports,
                        # 🔥 维度评分详情（前端短线博弈/长线博弈各面分数）
                        "维度评分详情": result.get("维度评分详情", []),
                        "技术面评分": result.get("技术面评分"),
                        "基本面评分": result.get("基本面评分"),
                        "情绪面评分": result.get("情绪面评分"),
                        "消息面评分": result.get("消息面评分"),
                        "资金面评分": result.get("资金面评分"),
                        "政策面评分": result.get("政策面评分"),
                        "解禁面评分": result.get("解禁面评分"),
                        "置信度详情": result.get("置信度详情", []),
                        "state": _sanitize_state_for_mongo(result.get("state", {})),
                        "decision": result.get("decision", {})
                    }}}
                )
                logger.info(f"💾 分析结果已保存 (web风格): {task_id}")
            else:
                logger.error("❌ MongoDB插入失败")

        except Exception as e:
            logger.error(f"❌ 保存分析结果失败: {task_id} - {e}")
            # 降级到简单保存
            try:
                simple_result = {
                    'task_id': task_id,
                    'success': result.get('success', True),
                    'error': str(e),
                    'completed_at': now_tz().isoformat()
                }
                await db.analysis_tasks.update_one(
                    {"task_id": task_id},
                    {"$set": {"result": simple_result}}
                )
                logger.info(f"💾 使用简化结果保存: {task_id}")
            except Exception as fallback_error:
                logger.error(f"❌ 简化保存也失败: {task_id} - {fallback_error}")

    async def _save_analysis_results_complete(self, task_id: str, result: dict[str, Any]):
        """完整的分析结果保存 - 完全采用web目录的双重保存方式"""
        try:
            # 调试：打印result中的所有键
            logger.info(f"🔍 [调试] result中的所有键: {list(result.keys())}")
            logger.info(f"🔍 [调试] stock_code: {result.get('stock_code', 'NOT_FOUND')}")
            logger.info(f"🔍 [调试] stock_symbol: {result.get('stock_symbol', 'NOT_FOUND')}")

            # 优先使用stock_symbol，如果没有则使用stock_code
            stock_symbol = result.get('stock_symbol') or result.get('stock_code', 'UNKNOWN')
            logger.info(f"💾 开始完整保存分析结果: {stock_symbol}")

            # 1. 保存分模块报告到本地目录
            logger.info("📁 [本地保存] 开始保存分模块报告到本地目录")
            local_files = await self._save_modular_reports_to_data_dir(result, stock_symbol)
            if local_files:
                logger.info(f"✅ [本地保存] 已保存 {len(local_files)} 个本地报告文件")
                for module, path in local_files.items():
                    logger.info(f"  - {module}: {path}")
            else:
                logger.warning("⚠️ [本地保存] 本地报告文件保存失败")

            # 2. 保存分析报告到数据库
            logger.info("🗄️ [数据库保存] 开始保存分析报告到数据库")
            await self._save_analysis_result_web_style(task_id, result)
            logger.info("✅ [数据库保存] 分析报告已成功保存到数据库")

            # 3. 记录保存结果
            if local_files:
                logger.info("✅ 分析报告已保存到数据库和本地文件")
            else:
                logger.warning("⚠️ 数据库保存成功，但本地文件保存失败")

        except Exception as save_error:
            logger.error(f"❌ [完整保存] 保存分析报告时发生错误: {str(save_error)}")
            # 降级到仅数据库保存
            try:
                await self._save_analysis_result_web_style(task_id, result)
                logger.info(f"💾 降级保存成功 (仅数据库): {task_id}")
            except Exception as fallback_error:
                logger.error(f"❌ 降级保存也失败: {task_id} - {fallback_error}")

    async def _save_modular_reports_to_data_dir(self, result: dict[str, Any], stock_symbol: str) -> dict[str, str]:
        """保存分模块报告到data目录 - 完全采用web目录的文件结构"""
        try:
            import json
            import os
            from datetime import datetime
            from pathlib import Path

            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent

            # 确定results目录路径 - 与web目录保持一致
            results_dir_env = os.getenv("TRADINGAGENTS_RESULTS_DIR")
            if results_dir_env:
                if not os.path.isabs(results_dir_env):
                    results_dir = project_root / results_dir_env
                else:
                    results_dir = Path(results_dir_env)
            else:
                # 默认使用data目录而不是results目录
                results_dir = project_root / "data" / "analysis_results"

            # 创建股票专用目录 - 完全按照web目录的结构
            analysis_date_raw = result.get('analysis_date', now_tz())

            # 确保 analysis_date 是字符串格式
            if isinstance(analysis_date_raw, datetime):
                analysis_date_str = analysis_date_raw.strftime('%Y-%m-%d')
            elif isinstance(analysis_date_raw, str):
                # 如果已经是字符串，检查格式
                try:
                    # 尝试解析日期字符串，确保格式正确
                    datetime.strptime(analysis_date_raw, '%Y-%m-%d')
                    analysis_date_str = analysis_date_raw
                except ValueError:
                    # 如果格式不正确，使用当前日期
                    analysis_date_str = now_tz().strftime('%Y-%m-%d')
            else:
                # 其他类型，使用当前日期
                analysis_date_str = now_tz().strftime('%Y-%m-%d')

            stock_dir = results_dir / stock_symbol / analysis_date_str
            reports_dir = stock_dir / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            # 创建message_tool.log文件 - 与web目录保持一致
            log_file = stock_dir / "message_tool.log"
            log_file.touch(exist_ok=True)

            logger.info(f"📁 创建分析结果目录: {reports_dir}")
            logger.info(f"🔍 [调试] analysis_date_raw 类型: {type(analysis_date_raw)}, 值: {analysis_date_raw}")
            logger.info(f"🔍 [调试] analysis_date_str: {analysis_date_str}")
            logger.info(f"🔍 [调试] 完整路径: {os.path.normpath(str(reports_dir))}")

            state = result.get('state', {})
            saved_files = {}

            # 定义报告模块映射 - 完全按照web目录的定义
            report_modules = {
                'market_report': {
                    'filename': 'market_report.md',
                    'title': f'{stock_symbol} 股票技术分析报告',
                    'state_key': 'market_report'
                },
                'sentiment_report': {
                    'filename': 'sentiment_report.md',
                    'title': f'{stock_symbol} 市场情绪分析报告',
                    'state_key': 'sentiment_report'
                },
                'news_report': {
                    'filename': 'news_report.md',
                    'title': f'{stock_symbol} 新闻事件分析报告',
                    'state_key': 'news_report'
                },
                'fundamentals_report': {
                    'filename': 'fundamentals_report.md',
                    'title': f'{stock_symbol} 基本面分析报告',
                    'state_key': 'fundamentals_report'
                },
                'policy_report': {
                    'filename': 'policy_report.md',
                    'title': f'{stock_symbol} 政策分析报告',
                    'state_key': 'policy_report'
                },
                'hot_money_report': {
                    'filename': 'hot_money_report.md',
                    'title': f'{stock_symbol} 游资追踪报告',
                    'state_key': 'hot_money_report'
                },
                'lockup_report': {
                    'filename': 'lockup_report.md',
                    'title': f'{stock_symbol} 解禁追踪报告',
                    'state_key': 'lockup_report'
                },
                'investment_plan': {
                    'filename': 'investment_plan.md',
                    'title': f'{stock_symbol} 投资决策报告',
                    'state_key': 'investment_plan'
                },
                'trader_investment_plan': {
                    'filename': 'trader_investment_plan.md',
                    'title': f'{stock_symbol} 交易计划报告',
                    'state_key': 'trader_investment_plan'
                },
                'risk_control_decision': {
                    'filename': 'risk_control_decision.md',
                    'title': f'{stock_symbol} 风控约束报告',
                    'state_key': 'risk_control_decision'
                },
                'final_trade_decision': {
                    'filename': 'final_trade_decision.md',
                    'title': f'{stock_symbol} 最终投资决策',
                    'state_key': 'final_trade_decision'
                },
                'investment_debate_state': {
                    'filename': 'research_team_decision.md',
                    'title': f'{stock_symbol} 研究团队决策报告',
                    'state_key': 'investment_debate_state'
                },
                'risk_debate_state': {
                    'filename': 'risk_management_decision.md',
                    'title': f'{stock_symbol} 风险管理团队决策报告',
                    'state_key': 'risk_debate_state'
                }
            }

            # 保存各模块报告 - 完全按照web目录的方式
            for module_key, module_info in report_modules.items():
                try:
                    state_key = module_info['state_key']
                    if state_key in state:
                        # 提取模块内容
                        module_content = state[state_key]
                        report_content = module_content if isinstance(module_content, str) else str(module_content)

                        # 保存到文件 - 使用web目录的文件名
                        file_path = reports_dir / module_info['filename']
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(report_content)

                        saved_files[module_key] = str(file_path)
                        logger.info(f"✅ 保存模块报告: {file_path}")

                except Exception as e:
                    logger.warning(f"⚠️ 保存模块 {module_key} 失败: {e}")

            # 保存最终决策报告 - 完全按照web目录的方式
            decision = result.get('decision', {})
            if decision:
                decision_content = f"# {stock_symbol} 最终投资决策\n\n"

                if isinstance(decision, dict):
                    decision_content += "## 投资建议\n\n"
                    decision_content += f"**行动**: {decision.get('action', 'N/A')}\n\n"
                    decision_content += f"**置信度**: {decision.get('confidence', 0):.1%}\n\n"
                    decision_content += f"**风险评分**: {decision.get('risk_score', 0):.1%}\n\n"
                    decision_content += f"**目标价位**: {decision.get('target_price', 'N/A')}\n\n"
                    decision_content += f"## 分析推理\n\n{decision.get('reasoning', '暂无分析推理')}\n\n"
                else:
                    decision_content += f"{str(decision)}\n\n"

                decision_file = reports_dir / "final_trade_decision.md"
                with open(decision_file, 'w', encoding='utf-8') as f:
                    f.write(decision_content)

                saved_files['final_trade_decision'] = str(decision_file)
                logger.info(f"✅ 保存最终决策: {decision_file}")

            # 保存分析元数据文件 - 完全按照web目录的方式
            metadata = {
                'stock_symbol': stock_symbol,
                'analysis_date': analysis_date_str,
                'timestamp': now_tz().isoformat(),
                'analysts': result.get('analysts', []),
                'status': 'completed',
                'reports_count': len(saved_files),
                'report_types': list(saved_files.keys())
            }

            metadata_file = reports_dir.parent / "analysis_metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ 保存分析元数据: {metadata_file}")
            logger.info(f"✅ 分模块报告保存完成，共保存 {len(saved_files)} 个文件")
            logger.info(f"📁 保存目录: {os.path.normpath(str(reports_dir))}")

            return saved_files

        except Exception as e:
            logger.error(f"❌ 保存分模块报告失败: {e}")
            import traceback
            logger.error(f"❌ 详细错误: {traceback.format_exc()}")
            return {}

# 重复的 get_task_status 方法已删除，使用第469行的内存版本


# 全局服务实例
_analysis_service = None

def get_simple_analysis_service() -> SimpleAnalysisService:
    """获取分析服务实例"""
    global _analysis_service
    if _analysis_service is None:
        logger.info("🔧 [单例] 创建新的 SimpleAnalysisService 实例")
        _analysis_service = SimpleAnalysisService()
    else:
        logger.info(f"🔧 [单例] 返回现有的 SimpleAnalysisService 实例: {id(_analysis_service)}")
    return _analysis_service
