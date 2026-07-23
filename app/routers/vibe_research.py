"""
Vibe-Research 融合模块 API 路由
提供复盘（大盘指数/市场情绪/资金流/短线情绪/成交额榜）、资讯雷达、板块、AI对话等接口
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import json
import os
import asyncio
from datetime import datetime, timedelta

from app.core.response import ok
from app.services.newsradar import get_radar_cached, fetch_radar
from app.services.market_overview import (
    get_overview, get_short_term_emotion, get_turnover_top, get_global_indices
)
from app.services import vibe_astock as astock
from app.services.news_data_service import get_news_data_service, NewsQueryParams

router = APIRouter(prefix="/api/vibe", tags=["Vibe-Research"])
logger = logging.getLogger("webapi")


async def get_optional_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """获取当前用户信息（可选）：有token则验证，没有则返回guest用户"""
    if not authorization:
        return {"user_id": "guest", "username": "guest", "is_guest": True}
    
    try:
        from app.routers.auth_db import get_current_user
        user = await get_current_user(authorization)
        user["is_guest"] = False
        return user
    except Exception:
        return {"user_id": "guest", "username": "guest", "is_guest": True}


def _get_user_id(user: dict) -> str:
    """从用户对象获取用户ID"""
    if user.get("is_guest"):
        return "guest"
    return str(user.get("id") or user.get("user_id") or "guest")


# ---------------------------------------------------------------------------
# 复盘模块
# ---------------------------------------------------------------------------

@router.get("/indices")
async def indices(current_user: dict = Depends(get_optional_current_user)):
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）"""
    try:
        data = astock.index_quote()
        return ok(data)
    except Exception as e:
        logger.error(f"大盘指数异常: {e}")
        return ok([])


@router.get("/global-indices")
async def global_indices(current_user: dict = Depends(get_optional_current_user)):
    """全球指数快照（美股/港股），分级TTL缓存"""
    try:
        data = await get_global_indices()
        return ok(data)
    except Exception as e:
        logger.error(f"全球指数异常: {e}")
        return ok([])


@router.get("/market/overview")
async def market_overview(current_user: dict = Depends(get_optional_current_user)):
    """市场情绪 + 板块资金流（Redis分级TTL缓存）"""
    try:
        data = await get_overview()
        return ok(data)
    except Exception as e:
        logger.error(f"市场总览异常: {e}")
        return ok({"sentiment": {}, "sectors": [], "updated": ""})


@router.get("/market/emotion")
async def market_emotion(current_user: dict = Depends(get_optional_current_user)):
    """短线情绪（连板梯队/封板率/炸板率/晋级率），分级TTL缓存"""
    try:
        data = await get_short_term_emotion()
        return ok(data)
    except Exception as e:
        logger.error(f"短线情绪异常: {e}")
        return ok({})


@router.get("/market/turnover-top")
async def market_turnover_top(current_user: dict = Depends(get_optional_current_user)):
    """全市场成交额Top20，分级TTL缓存"""
    try:
        data = await get_turnover_top()
        return ok(data)
    except Exception as e:
        logger.error(f"成交额榜异常: {e}")
        return ok({"stocks": [], "updated": ""})


@router.get("/quotes")
async def quotes(codes: str, current_user: dict = Depends(get_optional_current_user)):
    """批量个股实时行情（逗号分隔代码）- 统一行情服务"""
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if not code_list:
            return ok([])

        from app.services.unified_quotes import get_unified_quotes
        data = get_unified_quotes(code_list)

        out = []
        for code, q in data.items():
            item = {
                "code": code,
                "name": q.get("name", ""),
                "is_st": q.get("is_st", False),
                "price": q.get("price"),
                "change_pct": q.get("change_pct"),
                "change_amt": q.get("change_amt"),
                "pe_ttm": q.get("pe_ttm"),
                "pb": q.get("pb"),
                "mcap_yi": q.get("mcap_yi"),
                "float_mcap_yi": q.get("float_mcap_yi"),
                "amount_wan": q.get("amount_wan"),
                "turnover_pct": q.get("turnover_pct"),
            }
            validation = q.get("_validation")
            if validation:
                item["_validation"] = validation
            if q.get("is_st"):
                if not validation:
                    item["_validation"] = {"passed": True, "errors": [], "warnings": []}
                item["_validation"]["warnings"].append("⚠️ ST股票：存在退市风险，投资需谨慎")
            out.append(item)
        return ok(out)
    except Exception as e:
        logger.error(f"批量行情异常: {e}")
        return ok([])


# ---------------------------------------------------------------------------
# 资讯模块
# ---------------------------------------------------------------------------

# ==================== 新闻数据统一服务辅助函数 ====================

def _convert_vibe_news_to_standard(vibe_news: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """将Vibe格式（中文键名）的新闻转换为标准格式（英文键名）"""
    title = vibe_news.get("新闻标题", "")
    url = vibe_news.get("新闻链接", "")
    publish_time_str = vibe_news.get("发布时间", "")
    source = vibe_news.get("文章来源", "") or vibe_news.get("新闻来源", "")

    publish_time = None
    if publish_time_str:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                publish_time = datetime.strptime(publish_time_str, fmt)
                break
            except ValueError:
                continue

    title_lower = title.lower()
    positive_words = ["增长", "上涨", "利好", "盈利", "成功", "突破", "创新", "优秀"]
    negative_words = ["下跌", "亏损", "风险", "问题", "困难", "下滑", "减少", "警告"]
    positive_count = sum(1 for w in positive_words if w in title_lower)
    negative_count = sum(1 for w in negative_words if w in title_lower)
    if positive_count > negative_count:
        sentiment = "positive"
    elif negative_count > positive_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    high_importance_words = ["重大", "紧急", "突发", "年报", "业绩", "重组", "收购"]
    medium_importance_words = ["公告", "通知", "变更", "调整", "计划"]
    if any(w in title_lower for w in high_importance_words):
        importance = "high"
    elif any(w in title_lower for w in medium_importance_words):
        importance = "medium"
    else:
        importance = "low"

    category_keywords = {
        "company_announcement": ["年报", "季报", "业绩", "财报", "公告"],
        "policy_news": ["政策", "央行", "监管", "法规"],
        "market_news": ["市场", "行情", "指数", "板块"],
        "research_report": ["研报", "分析", "评级", "推荐"],
    }
    category = "general"
    for cat, keywords in category_keywords.items():
        if any(kw in title_lower for kw in keywords):
            category = cat
            break

    return {
        "symbol": symbol,
        "title": title,
        "content": "",
        "summary": "",
        "url": url,
        "source": source,
        "author": "",
        "publish_time": publish_time,
        "category": category,
        "sentiment": sentiment,
        "importance": importance,
        "keywords": [],
        "data_source": "eastmoney"
    }


def _convert_standard_news_to_vibe(standard_news: Dict[str, Any]) -> Dict[str, Any]:
    """将标准格式（英文键名）的新闻转换为前端统一格式（英文键名）"""
    publish_time = standard_news.get("publish_time")
    if isinstance(publish_time, datetime):
        publish_time_str = publish_time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        publish_time_str = str(publish_time) if publish_time else ""

    return {
        "title": standard_news.get("title", ""),
        "url": standard_news.get("url", ""),
        "publish_time": publish_time_str,
        "source": standard_news.get("source", ""),
        "content": standard_news.get("summary", "") or (standard_news.get("content", "")[:200] if standard_news.get("content") else ""),
        "symbol": standard_news.get("symbol", ""),
        "stock_codes": [standard_news.get("symbol", "")] if standard_news.get("symbol") else [],
    }


async def _fetch_and_save_stock_news(code: str, limit: int = 20) -> List[Dict[str, Any]]:
    """从东财获取股票新闻并保存到数据库，返回统一格式的新闻列表"""
    try:
        vibe_news_list = astock.stock_news(code, limit)
        if not vibe_news_list:
            return []

        standard_news_list = []
        for vibe_news in vibe_news_list:
            standard = _convert_vibe_news_to_standard(vibe_news, code)
            if standard["title"] and standard["url"]:
                standard_news_list.append(standard)

        if standard_news_list:
            try:
                service = await get_news_data_service()
                saved_count = await service.save_news_data(
                    standard_news_list,
                    data_source="eastmoney",
                    market="CN"
                )
                logger.info(f"💾 股票 {code} 新闻保存到数据库: {saved_count}条")
            except Exception as e:
                logger.warning(f"⚠️ 保存新闻到数据库失败: {e}")

        return [_convert_standard_news_to_vibe(n) for n in standard_news_list]
    except Exception as e:
        logger.error(f"❌ 获取并保存股票新闻失败 {code}: {e}")
        return []


@router.get("/radar")
async def radar(current_user: dict = Depends(get_optional_current_user)):
    """资讯雷达：12赛道公开RSS资讯（Redis分级缓存）"""
    try:
        data = await get_radar_cached(force=False)
        return ok(data)
    except Exception as e:
        logger.warning(f"资讯雷达缓存读取异常，降级到本地缓存: {e}")
        # 降级：尝试本地文件缓存，再降级到骨架
        try:
            from app.services.newsradar import load_cache, skeleton
            cached = load_cache()
            if cached:
                return ok(cached)
        except Exception:
            pass
        return ok(skeleton())


@router.post("/radar/refresh")
async def radar_refresh(current_user: dict = Depends(get_optional_current_user)):
    """强制刷新资讯雷达（抓取全部RSS源）"""
    try:
        data = fetch_radar()
        return ok(data)
    except Exception as e:
        logger.warning(f"资讯雷达刷新异常，降级到本地缓存: {e}")
        try:
            from app.services.newsradar import load_cache, skeleton
            cached = load_cache()
            if cached:
                return ok(cached)
        except Exception:
            pass
        return ok(skeleton())


@router.get("/announcements")
async def announcements(code: str, limit: int = 15, current_user: dict = Depends(get_optional_current_user)):
    """个股近期公告（东财公开接口）"""
    try:
        data = astock.announcements(code, limit)
        return ok(data)
    except Exception as e:
        logger.error(f"个股公告异常: {e}")
        return ok([])


@router.get("/announcements/batch")
async def announcements_batch(codes: str, limit: int = 10, current_user: dict = Depends(get_optional_current_user)):
    """批量获取多只股票公告（逗号分隔代码）"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return ok([])
    
    results = []
    for code in code_list[:20]:
        try:
            anns = astock.announcements(code, limit)
            for item in anns:
                item["stock_code"] = code
                results.append(item)
        except Exception as e:
            logger.warning(f"获取股票 {code} 公告失败: {e}")
    
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return ok(results[:limit * 3])


@router.get("/news")
async def stock_news(code: str, limit: int = 20, since: str = "", current_user: dict = Depends(get_optional_current_user)):
    """个股新闻（优先数据库，无数据时从东财实时获取并存入数据库），支持 since 参数增量更新"""
    try:
        service = await get_news_data_service()

        since_time = None
        if since:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                try:
                    since_time = datetime.strptime(since, fmt)
                    break
                except ValueError:
                    continue

        params = NewsQueryParams(
            symbol=code,
            start_time=since_time,
            limit=limit,
            sort_by="publish_time",
            sort_order=-1
        )
        db_news = await service.query_news(params)

        if len(db_news) >= limit:
            vibe_news = [_convert_standard_news_to_vibe(n) for n in db_news[:limit]]
            logger.info(f"📰 股票 {code} 新闻从数据库获取: {len(vibe_news)}条")
            return ok(vibe_news)

        logger.info(f"📰 数据库新闻不足，从东财实时获取: {code}")
        fresh_news = await _fetch_and_save_stock_news(code, max(limit, 30))

        if since:
            fresh_news = [item for item in fresh_news if item.get("publish_time", "") > since]

        return ok(fresh_news[:limit])
    except Exception as e:
        logger.error(f"个股新闻异常: {e}")
        return ok([])


@router.get("/news/batch")
async def news_batch(codes: str, limit: int = 10, since: str = "", current_user: dict = Depends(get_optional_current_user)):
    """批量获取多只股票新闻（优先数据库，无数据时实时获取），自动去重，支持 since 增量更新"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return ok([])

    try:
        service = await get_news_data_service()

        since_time = None
        if since:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                try:
                    since_time = datetime.strptime(since, fmt)
                    break
                except ValueError:
                    continue

        all_db_news = []
        missing_codes = []

        for code in code_list[:20]:
            try:
                params = NewsQueryParams(
                    symbol=code,
                    start_time=since_time,
                    limit=limit,
                    sort_by="publish_time",
                    sort_order=-1
                )
                db_news = await service.query_news(params)
                if len(db_news) >= limit:
                    all_db_news.extend(db_news[:limit])
                else:
                    missing_codes.append(code)
            except Exception as e:
                logger.warning(f"从数据库获取股票 {code} 新闻失败: {e}")
                missing_codes.append(code)

        if missing_codes:
            logger.info(f"📰 {len(missing_codes)}只股票新闻数据不足，从东财实时获取")
            for code in missing_codes:
                try:
                    fresh_news = await _fetch_and_save_stock_news(code, max(limit, 20))
                    if since:
                        fresh_news = [item for item in fresh_news if item.get("publish_time", "") > since]
                    all_db_news.extend([_convert_vibe_news_to_standard(n, code) for n in fresh_news])
                except Exception as e:
                    logger.warning(f"获取股票 {code} 新闻失败: {e}")

        seen = {}
        for news_item in all_db_news:
            title = news_item.get("title", "").strip()
            if not title:
                continue
            symbol = news_item.get("symbol", "")
            if title not in seen:
                vibe_item = _convert_standard_news_to_vibe(news_item)
                vibe_item["stock_codes"] = [symbol] if symbol else []
                seen[title] = vibe_item
            else:
                if symbol and symbol not in seen[title]["stock_codes"]:
                    seen[title]["stock_codes"].append(symbol)
                publish_time = news_item.get("publish_time")
                if publish_time:
                    if isinstance(publish_time, datetime):
                        pt_str = publish_time.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        pt_str = str(publish_time)
                    if pt_str < seen[title].get("publish_time", ""):
                        seen[title]["publish_time"] = pt_str

        results = list(seen.values())
        results.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
        return ok(results[:limit * 3])
    except Exception as e:
        logger.error(f"批量新闻异常: {e}")
        return ok([])


# ---------------------------------------------------------------------------
# 板块模块
# ---------------------------------------------------------------------------

@router.get("/sectors")
async def sectors(current_user: dict = Depends(get_optional_current_user)):
    """板块中心：热门赛道产业链骨架（静态数据）"""
    sectors_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sectors.json")
    try:
        with open(sectors_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ok(data)
    except Exception as e:
        logger.error(f"板块数据读取异常: {e}")
        raise HTTPException(500, f"板块数据读取异常: {e}")


# ---------------------------------------------------------------------------
# AI 对话模块（复用系统已配置的 LLM）
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: str = ""


def _get_llm_config():
    """从系统配置中获取第一个可用的 LLM 配置（有 API Key 的）"""
    try:
        from app.core.unified_config import unified_config
        from app.services.config_service import ConfigService
        cs = ConfigService()

        llm_configs = unified_config.get_llm_configs()
        quick_model = unified_config.get_quick_analysis_model()

        # 默认 api_base 映射
        default_base = {
            "deepseek": "https://api.deepseek.com",
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai": "https://api.openai.com/v1",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }

        # 优先找快速分析模型
        for cfg in llm_configs:
            if cfg.model_name == quick_model and cfg.enabled:
                api_key = cs._get_env_api_key(cfg.provider)
                if api_key:
                    return {
                        "model": cfg.model_name,
                        "api_base": cfg.api_base or default_base.get(cfg.provider, ""),
                        "api_key": api_key,
                        "temperature": cfg.temperature,
                        "max_tokens": cfg.max_tokens,
                    }

        # 回退：找第一个有 API Key 的启用配置
        for cfg in llm_configs:
            if cfg.enabled:
                api_key = cs._get_env_api_key(cfg.provider)
                if api_key:
                    return {
                        "model": cfg.model_name,
                        "api_base": cfg.api_base or default_base.get(cfg.provider, ""),
                        "api_key": api_key,
                        "temperature": cfg.temperature,
                        "max_tokens": cfg.max_tokens,
                    }

        return None
    except Exception as e:
        logger.error(f"获取LLM配置失败: {e}")
        return None


SYSTEM_PROMPT = (
    "你是一个专业的A股投研助理。你可以基于用户提供的客观数据进行分析和总结。\n"
    "硬性规则：\n"
    "- 只做信息整理、数据解读与多视角分析\n"
    "- 不推荐任何具体买卖、不预测涨跌与价位、不给买卖时机、不承诺收益\n"
    "- 需要基于用户提供的客观数据回答，不要编造数字\n"
    "- 回答使用中文，简洁专业\n"
)


@router.post("/chat")
async def chat(req: ChatRequest, current_user: dict = Depends(get_optional_current_user)):
    """AI 对话（流式 NDJSON）。复用系统已配置的 LLM。"""
    cfg = _get_llm_config()
    if not cfg or not cfg.get("api_key"):
        def err_gen():
            yield json.dumps({"type": "error", "message": "系统尚未配置 AI 模型或 API Key，请先在设置中配置。"}, ensure_ascii=False) + "\n"
        return StreamingResponse(err_gen(), media_type="application/x-ndjson")

    import requests

    messages = [{"role": "system", "content": SYSTEM_PROMPT + (f"\n当前页面上下文：\n{req.context}" if req.context else "")}]
    messages.extend({"role": m.role, "content": m.content} for m in req.messages)

    api_base = cfg["api_base"].rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base = api_base + "/chat/completions"

    def gen():
        try:
            resp = requests.post(
                api_base,
                json={
                    "model": cfg["model"],
                    "messages": messages,
                    "temperature": cfg.get("temperature", 0.7),
                    "max_tokens": cfg.get("max_tokens", 4000),
                    "stream": True,
                },
                headers={
                    "Authorization": f"Bearer {cfg['api_key']}",
                    "Content-Type": "application/json",
                },
                stream=True,
                timeout=120,
            )
            if resp.status_code != 200:
                err_msg = resp.text[:500]
                yield json.dumps({"type": "error", "message": f"AI 服务返回错误 ({resp.status_code}): {err_msg}"}, ensure_ascii=False) + "\n"
                return

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield json.dumps({"type": "delta", "text": text}, ensure_ascii=False) + "\n"
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except requests.exceptions.Timeout:
            yield json.dumps({"type": "error", "message": "AI 响应超时，请稍后重试。"}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# 用户数据模块（研究笔记 + 关注股票）
# ---------------------------------------------------------------------------

@router.get("/notes")
async def get_notes(kind: Optional[str] = None, current_user: dict = Depends(get_optional_current_user)):
    """获取研究笔记列表"""
    try:
        from app.services.research_notes_service import research_notes_service
        uid = _get_user_id(current_user)
        notes = await research_notes_service.get_user_notes(uid, kind)
        return ok(notes)
    except Exception as e:
        logger.error(f"获取研究笔记异常: {e}")
        return ok([])


class AddNoteRequest(BaseModel):
    kind: str
    title: str
    content: str


@router.post("/notes")
async def add_note(req: AddNoteRequest, current_user: dict = Depends(get_optional_current_user)):
    """添加研究笔记"""
    try:
        from app.services.research_notes_service import research_notes_service
        uid = _get_user_id(current_user)
        note = await research_notes_service.add_note(uid, req.kind, req.title, req.content)
        if note:
            return ok(note)
        else:
            return ok(None)
    except Exception as e:
        logger.error(f"添加研究笔记异常: {e}")
        return ok(None)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, current_user: dict = Depends(get_optional_current_user)):
    """删除研究笔记"""
    try:
        from app.services.research_notes_service import research_notes_service
        uid = _get_user_id(current_user)
        success = await research_notes_service.delete_note(uid, note_id)
        return ok({"success": success})
    except Exception as e:
        logger.error(f"删除研究笔记异常: {e}")
        return ok({"success": False})


@router.delete("/notes")
async def clear_notes(current_user: dict = Depends(get_optional_current_user)):
    """清空研究笔记"""
    try:
        from app.services.research_notes_service import research_notes_service
        uid = _get_user_id(current_user)
        success = await research_notes_service.clear_notes(uid)
        return ok({"success": success})
    except Exception as e:
        logger.error(f"清空研究笔记异常: {e}")
        return ok({"success": False})


@router.get("/watchlist")
async def get_watchlist(current_user: dict = Depends(get_optional_current_user)):
    """获取关注股票列表（简化版：仅返回股票代码列表，使用FavoritesService）"""
    try:
        from app.services.favorites_service import favorites_service
        uid = _get_user_id(current_user)
        favorites = await favorites_service.get_user_favorites(uid)
        codes = [fav.get("stock_code", "") for fav in favorites if fav.get("stock_code")]
        return ok(codes)
    except Exception as e:
        logger.error(f"获取关注股票异常: {e}")
        return ok([])


class WatchlistRequest(BaseModel):
    code: str
    name: Optional[str] = ""


@router.post("/watchlist")
async def add_to_watchlist(req: WatchlistRequest, current_user: dict = Depends(get_optional_current_user)):
    """添加股票到关注列表"""
    try:
        from app.services.favorites_service import favorites_service
        uid = _get_user_id(current_user)
        success = await favorites_service.add_favorite(
            user_id=uid,
            stock_code=req.code,
            stock_name=req.name or req.code,
            market="A股"
        )
        return ok({"success": success})
    except Exception as e:
        logger.error(f"添加关注股票异常: {e}")
        return ok({"success": False})


@router.delete("/watchlist/{code}")
async def remove_from_watchlist(code: str, current_user: dict = Depends(get_optional_current_user)):
    """从关注列表移除股票"""
    try:
        from app.services.favorites_service import favorites_service
        uid = _get_user_id(current_user)
        success = await favorites_service.remove_favorite(uid, code)
        return ok({"success": success})
    except Exception as e:
        logger.error(f"移除关注股票异常: {e}")
        return ok({"success": False})
