"""
股票详情相关API
- 统一响应包: {success, data, message, timestamp}
- 所有端点均需鉴权 (Bearer Token)
- 路径前缀在 main.py 中挂载为 /api，当前路由自身前缀为 /stocks
"""
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, status, Query
from datetime import datetime
import asyncio  # 🔥 添加 asyncio 导入
import logging
import os
import re

from app.routers.auth_db import get_current_user
from app.core.database import get_mongo_db
from app.core.response import ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["stocks"])


def _zfill_code(code: str) -> str:
    try:
        s = str(code).strip()
        if len(s) == 6 and s.isdigit():
            return s
        return s.zfill(6)
    except Exception:
        return str(code)


def _detect_market_and_code(code: str) -> Tuple[str, str]:
    """
    检测股票代码的市场类型并标准化代码

    Args:
        code: 股票代码

    Returns:
        (market, normalized_code): 市场类型和标准化后的代码
            - CN: A股（6位数字）
            - HK: 港股（4-5位数字或带.HK后缀）
            - US: 美股（字母代码）
    """
    code = code.strip().upper()

    # 港股：带.HK后缀
    if code.endswith('.HK'):
        return ('HK', code[:-3].zfill(5))  # 移除.HK，补齐到5位

    # 美股：纯字母
    if re.match(r'^[A-Z]+$', code):
        return ('US', code)

    # 港股：4-5位数字
    if re.match(r'^\d{4,5}$', code):
        return ('HK', code.zfill(5))  # 补齐到5位

    # A股：6位数字
    if re.match(r'^\d{6}$', code):
        return ('CN', code)

    # 默认当作A股处理
    return ('CN', _zfill_code(code))


async def _fetch_news_from_multiple_sources(code: str, days: int = 30, limit: int = 50) -> List[Dict]:
    """
    从多个数据源获取新闻数据（财联社、东方财富、同花顺等）

    Args:
        code: 股票代码（6位数字）
        days: 查询天数
        limit: 返回条数限制

    Returns:
        新闻列表
    """
    import asyncio
    items = []
    code6 = str(code).zfill(6)

    # 数据源1: AKShare 东方财富新闻
    async def _fetch_eastmoney_news():
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_news_em, symbol=code6)
            if df is not None and not df.empty:
                result = []
                for _, row in df.head(limit).iterrows():
                    result.append({
                        "publish_time": str(row.get('发布时间') or row.get('时间') or ''),
                        "title": str(row.get('新闻标题') or row.get('标题') or ''),
                        "source": str(row.get('文章来源') or row.get('来源') or '东方财富'),
                        "url": str(row.get('新闻链接') or row.get('链接') or ''),
                        "type": "news",
                        "content": "",
                        "summary": ""
                    })
                return result
        except Exception as e:
            logger.warning(f"⚠️ 东方财富新闻获取失败: {e}")
        return []

    # 数据源2: AKShare 股吧热点
    async def _fetch_guba_news():
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_guba_em, symbol=code6)
            if df is not None and not df.empty:
                result = []
                for _, row in df.head(min(limit, 20)).iterrows():
                    result.append({
                        "publish_time": str(row.get('发布时间') or row.get('时间') or ''),
                        "title": str(row.get('帖子标题') or row.get('标题') or ''),
                        "source": "股吧",
                        "url": str(row.get('帖子链接') or row.get('链接') or ''),
                        "type": "news",
                        "content": "",
                        "summary": ""
                    })
                return result
        except Exception as e:
            logger.warning(f"⚠️ 股吧热点获取失败: {e}")
        return []

    # 数据源3: AKShare 互动易（投资者互动）
    async def _fetch_interactive_news():
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_irm_ans_cninfo, symbol=code6)
            if df is not None and not df.empty:
                result = []
                for _, row in df.head(min(limit, 10)).iterrows():
                    result.append({
                        "publish_time": str(row.get('答复时间') or row.get('时间') or ''),
                        "title": str(row.get('提问内容') or row.get('标题') or '')[:50],
                        "source": "互动易",
                        "url": "",
                        "type": "news",
                        "content": str(row.get('答复内容') or ''),
                        "summary": ""
                    })
                return result
        except Exception as e:
            logger.warning(f"⚠️ 互动易获取失败: {e}")
        return []

    # 并发获取所有数据源
    try:
        results = await asyncio.gather(
            _fetch_eastmoney_news(),
            _fetch_guba_news(),
            _fetch_interactive_news(),
            return_exceptions=True
        )

        for result in results:
            if isinstance(result, list) and result:
                items.extend(result)

        # 去重（基于标题）
        seen_titles = set()
        unique_items = []
        for item in items:
            title = item.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_items.append(item)

        logger.info(f"📡 多数据源获取新闻: {code6}, 共 {len(unique_items)} 条")
        return unique_items[:limit]
    except Exception as e:
        logger.error(f"❌ 多数据源获取新闻失败: {e}")
        return items


@router.get("/{code}/quote", response_model=dict)
async def get_quote(
    code: str,
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取股票实时行情（支持A股/港股/美股）

    自动识别市场类型：
    - 6位数字 → A股
    - 4位数字或.HK → 港股
    - 纯字母 → 美股

    参数：
    - code: 股票代码
    - force_refresh: 是否强制刷新（跳过缓存）

    返回字段（data内，蛇形命名）:
      - code, name, market
      - price(close), change_percent(pct_chg), amount, prev_close(估算)
      - turnover_rate, amplitude（振幅，替代量比）
      - trade_date, updated_at
    """
    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新服务
    if market in ['HK', 'US']:
        from app.services.foreign_stock_service import ForeignStockService

        db = get_mongo_db()  # 不需要 await，直接返回数据库对象
        service = ForeignStockService(db=db)

        try:
            quote = await service.get_quote(market, normalized_code, force_refresh)
            return ok(data=quote)
        except Exception as e:
            logger.error(f"获取{market}股票{code}行情失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取行情失败: {str(e)}"
            )

    # A股：使用现有逻辑
    db = get_mongo_db()
    code6 = normalized_code

    # 🔥 如果强制刷新，直接从数据源获取最新数据（优先使用单只股票快速查询）
    if force_refresh:
        logger.info(f"🔄 强制刷新：尝试从数据源获取 {code6} 的最新行情")
        try:
            from app.services.data_sources.akshare_adapter import AKShareAdapter
            
            # 🔥 优先使用单只股票快速查询（约 1 秒），而不是全市场获取（约 25 秒）
            def _fetch_single_quote():
                try:
                    adapter = AKShareAdapter()
                    quote = adapter.get_realtime_quote_single(code6, timeout=5)
                    return quote, "akshare_single"
                except Exception as e:
                    logger.warning(f"⚠️ 单只股票快速查询失败: {e}")
                    return None, None
            
            # 使用 asyncio.wait_for 设置超时保护
            loop = asyncio.get_event_loop()
            try:
                q, source = await asyncio.wait_for(
                    loop.run_in_executor(None, _fetch_single_quote),
                    timeout=10.0  # 🔥 10秒超时（单只股票查询约 1 秒）
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ 单只股票快速查询超时（10秒），回退到全市场获取")
                q, source = None, None
            
            # 如果单只股票快速查询失败，回退到全市场获取
            if q is None:
                logger.info(f"🔄 单只股票快速查询失败，回退到全市场获取")
                from app.services.data_sources.manager import DataSourceManager
                manager = DataSourceManager()
                
                def _fetch_realtime():
                    try:
                        quotes_map, fallback_source = manager.get_realtime_quotes_with_fallback()
                        if quotes_map and code6 in quotes_map:
                            return quotes_map[code6], fallback_source
                        return None, None
                    except Exception as e:
                        logger.warning(f"⚠️ 获取实时行情异常: {e}")
                        return None, None
                
                try:
                    quotes_map_data, fallback_source = await asyncio.wait_for(
                        loop.run_in_executor(None, _fetch_realtime),
                        timeout=30.0  # 🔥 30秒超时（AKShare sina 接口约需 25 秒）
                    )
                    if quotes_map_data:
                        q = quotes_map_data
                        source = fallback_source
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ 全市场获取实时行情超时（30秒），使用缓存数据")
                    q = await db["market_quotes"].find_one({"code": code6}, {"_id": 0})

            if q:
                logger.info(f"✅ 从 {source} 获取到 {code6} 的实时行情: close={q.get('close')}, pct_chg={q.get('pct_chg')}")
                
                # 🔥 如果快速查询返回的数据缺少涨跌幅和昨收价，从缓存获取昨收价计算
                # 注意：数据库中存储的字段名可能是 pre_close 或 prev_close，需要兼容
                # 🔥 如果快速查询只返回当前价格（high==low==close），保留缓存中的振幅和高低价数据
                high_eq_low = (q.get("high") == q.get("low") and q.get("high") is not None)
                if q.get("pct_chg") is None or (q.get("pre_close") is None and q.get("prev_close") is None) or high_eq_low:
                    cached_quote = await db["market_quotes"].find_one({"code": code6}, {"_id": 0, "pre_close": 1, "prev_close": 1, "pct_chg": 1, "high": 1, "low": 1, "amplitude": 1})
                    if cached_quote:
                        # 兼容 pre_close 和 prev_close 两种字段名
                        cached_pre_close = cached_quote.get("pre_close") or cached_quote.get("prev_close")
                        cached_pct_chg = cached_quote.get("pct_chg")

                        # 使用缓存的昨收价计算涨跌幅
                        if q.get("pct_chg") is None and cached_pre_close and q.get("close") and cached_pre_close > 0:
                            q["pct_chg"] = (q["close"] / cached_pre_close - 1.0) * 100.0
                            logger.info(f"🔥 从缓存昨收价计算涨跌幅: pre_close={cached_pre_close}, pct_chg={q['pct_chg']}")

                        # 使用缓存的昨收价（统一存储为 prev_close）
                        if q.get("pre_close") is None and q.get("prev_close") is None and cached_pre_close:
                            q["prev_close"] = cached_pre_close

                        # 🔥 如果快速查询只返回当前价格（单时刻数据），保留缓存中的高低价和振幅
                        if high_eq_low:
                            cached_high = cached_quote.get("high")
                            cached_low = cached_quote.get("low")
                            cached_amplitude = cached_quote.get("amplitude")
                            if cached_high and cached_low and cached_high != cached_low:
                                q["high"] = cached_high
                                q["low"] = cached_low
                                logger.info(f"🔥 保留缓存的高低价: high={cached_high}, low={cached_low}")
                            if cached_amplitude:
                                # 直接保留缓存的振幅，避免重新计算为 0
                                pass  # 振幅会在后面重新计算，这里先跳过
                
                # 更新缓存（保留振幅和高低价数据，避免被快速查询覆盖）
                try:
                    update_data = {
                        "code": code6,
                        "updated_at": datetime.now()
                    }
                    # 只更新必要的实时数据字段
                    for key in ["close", "open", "volume", "amount", "pct_chg", "prev_close", "trade_date"]:
                        if q.get(key) is not None:
                            update_data[key] = q[key]

                    # 🔥 如果快速查询只返回当前价格（high==low），不更新 high/low/amplitude
                    # 保留缓存中的完整振幅数据
                    if not high_eq_low:
                        if q.get("high") is not None:
                            update_data["high"] = q["high"]
                        if q.get("low") is not None:
                            update_data["low"] = q["low"]

                    await db["market_quotes"].update_one(
                        {"code": code6},
                        {"$set": update_data},
                        upsert=True
                    )
                    logger.info(f"✅ 已更新 {code6} 的行情缓存（保留振幅数据）")
                except Exception as update_err:
                    logger.warning(f"⚠️ 更新行情缓存失败: {update_err}")
            else:
                # 数据源也没有数据，从缓存读取
                q = await db["market_quotes"].find_one({"code": code6}, {"_id": 0})
                logger.info(f"⚠️ 数据源未找到 {code6} 的行情，使用缓存数据")
        except Exception as e:
            logger.warning(f"⚠️ 强制刷新获取实时行情失败: {e}")
            # 失败时从缓存读取
            q = await db["market_quotes"].find_one({"code": code6}, {"_id": 0})
    else:
        # 非强制刷新，从缓存读取
        q = await db["market_quotes"].find_one({"code": code6}, {"_id": 0})

    # 🔥 回退：如果 MongoDB 无行情数据，从统一行情服务获取实时数据
    if not q:
        try:
            from app.services.unified_quotes import get_single_quote
            uq = await asyncio.to_thread(get_single_quote, code6)
            if uq:
                logger.info(f"🔄 MongoDB无行情，从统一行情服务获取 {code6}: price={uq.get('price')}")
                q = {
                    "code": code6,
                    "close": uq.get("price"),
                    "pct_chg": uq.get("change_pct"),
                    "amount": uq.get("amount_wan") * 10000 if uq.get("amount_wan") else None,
                    "open": uq.get("open"),
                    "high": uq.get("high"),
                    "low": uq.get("low"),
                    "pre_close": uq.get("last_close"),
                    "trade_date": datetime.now().strftime("%Y-%m-%d"),
                    "updated_at": datetime.now(),
                }
        except Exception as e:
            logger.warning(f"⚠️ 统一行情服务回退失败: {e}")

    # 🔥 调试日志：查看查询结果
    logger.info(f"🔍 查询 market_quotes: code={code6}")
    if q:
        logger.info(f"  ✅ 找到数据: volume={q.get('volume')}, amount={q.get('amount')}, volume_ratio={q.get('volume_ratio')}")
    else:
        logger.info(f"  ❌ 未找到数据")

    # 🔥 基础信息 - 按数据源优先级查询
    from app.core.unified_config import UnifiedConfigManager
    config = UnifiedConfigManager()
    data_source_configs = await config.get_data_source_configs_async()

    # 提取启用的数据源，按优先级排序
    enabled_sources = [
        ds.type.lower() for ds in data_source_configs
        if ds.enabled and ds.type.lower() in ['tushare', 'akshare', 'baostock']
    ]

    if not enabled_sources:
        enabled_sources = ['tushare', 'akshare', 'baostock']

    # 按优先级查询基础信息
    b = None
    for src in enabled_sources:
        b = await db["stock_basic_info"].find_one({"code": code6, "source": src}, {"_id": 0})
        if b:
            break

    # 如果所有数据源都没有，尝试不带 source 条件查询（兼容旧数据）
    if not b:
        b = await db["stock_basic_info"].find_one({"code": code6}, {"_id": 0})

    if not q and not b:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该股票的任何信息")

    close = (q or {}).get("close")
    pct = (q or {}).get("pct_chg")
    # 兼容 pre_close 和 prev_close 两种字段名
    pre_close_saved = (q or {}).get("pre_close") or (q or {}).get("prev_close")
    prev_close = pre_close_saved
    if prev_close is None:
        try:
            if close is not None and pct is not None:
                prev_close = round(float(close) / (1.0 + float(pct) / 100.0), 4)
        except Exception:
            prev_close = None

    # 🔥 优先从 market_quotes 获取 turnover_rate（实时数据）
    # 如果 market_quotes 中没有，再从 stock_basic_info 获取（日度数据）
    turnover_rate = (q or {}).get("turnover_rate")
    turnover_rate_date = None
    if turnover_rate is None:
        turnover_rate = (b or {}).get("turnover_rate")
        turnover_rate_date = (b or {}).get("trade_date")  # 来自日度数据
    else:
        turnover_rate_date = (q or {}).get("trade_date")  # 来自实时数据

    # 🔥 计算振幅（amplitude）替代量比（volume_ratio）
    # 振幅 = (最高价 - 最低价) / 昨收价 × 100%
    amplitude = None
    amplitude_date = None
    try:
        high = (q or {}).get("high")
        low = (q or {}).get("low")

        # 🔥 如果高低价相同（快速查询数据），尝试从缓存获取完整的高低价
        if high is not None and low is not None and high == low:
            cached_quote_amp = await db["market_quotes"].find_one({"code": code6}, {"_id": 0, "high": 1, "low": 1, "amplitude": 1})
            if cached_quote_amp:
                cached_high = cached_quote_amp.get("high")
                cached_low = cached_quote_amp.get("low")
                cached_amp = cached_quote_amp.get("amplitude")
                if cached_high and cached_low and cached_high != cached_low:
                    high = cached_high
                    low = cached_low
                    logger.info(f"🔥 从缓存获取完整高低价: high={high}, low={low}")
                elif cached_amp and cached_amp > 0:
                    amplitude = cached_amp
                    logger.info(f"🔥 直接使用缓存振幅: {amplitude}%")

        if amplitude is None:
            logger.info(f"🔍 计算振幅: high={high}, low={low}, prev_close={prev_close}")
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = round((float(high) - float(low)) / float(prev_close) * 100, 2)
                amplitude_date = (q or {}).get("trade_date")  # 来自实时数据
                logger.info(f"  ✅ 振幅计算成功: {amplitude}%")
            else:
                logger.warning(f"  ⚠️ 数据不完整，无法计算振幅")
    except Exception as e:
        logger.warning(f"  ❌ 计算振幅失败: {e}")
        amplitude = None

    data = {
        "code": code6,
        "name": (b or {}).get("name"),
        "market": (b or {}).get("market"),
        "price": close,
        "change_percent": pct,
        "amount": (q or {}).get("amount"),
        "volume": (q or {}).get("volume"),
        "open": (q or {}).get("open"),
        "high": (q or {}).get("high"),
        "low": (q or {}).get("low"),
        "prev_close": prev_close,
        # 🔥 优先使用实时数据，降级到日度数据
        "turnover_rate": turnover_rate,
        "amplitude": amplitude,  # 🔥 新增：振幅（替代量比）
        "turnover_rate_date": turnover_rate_date,  # 🔥 新增：换手率数据日期
        "amplitude_date": amplitude_date,  # 🔥 新增：振幅数据日期
        "trade_date": (q or {}).get("trade_date"),
        "updated_at": (q or {}).get("updated_at"),
    }

    # 🔥 数据约束验证：清理行情数据中的异常值
    try:
        from tradingagents.dataflows.data_validator import validate_stock_data
        validation_result = validate_stock_data(data, code6)
        data = validation_result["clean_data"]
    except Exception as e:
        logger.warning(f"⚠️ 行情数据验证失败: {e}")

    return ok(data)


@router.get("/{code}/fundamentals", response_model=dict)
async def get_fundamentals(
    code: str,
    source: Optional[str] = Query(None, description="数据源 (tushare/akshare/baostock/multi_source)"),
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取基础面快照（支持A股/港股/美股）

    数据来源优先级：
    1. stock_basic_info 集合（基础信息、估值指标）
    2. stock_financial_data 集合（财务指标：ROE、负债率等）

    参数：
    - code: 股票代码
    - source: 数据源（可选），默认按优先级：tushare > multi_source > akshare > baostock
    - force_refresh: 是否强制刷新（跳过缓存）
    """
    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新服务
    if market in ['HK', 'US']:
        from app.services.foreign_stock_service import ForeignStockService

        db = get_mongo_db()  # 不需要 await，直接返回数据库对象
        service = ForeignStockService(db=db)

        try:
            info = await service.get_basic_info(market, normalized_code, force_refresh)
            return ok(data=info)
        except Exception as e:
            logger.error(f"获取{market}股票{code}基础信息失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取基础信息失败: {str(e)}"
            )

    # A股：使用现有逻辑
    db = get_mongo_db()
    code6 = normalized_code

    # 1. 获取基础信息（支持数据源筛选）
    query = {"code": code6}

    if source:
        # 指定数据源
        query["source"] = source
        b = await db["stock_basic_info"].find_one(query, {"_id": 0})
        if not b:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到该股票在数据源 {source} 中的基础信息"
            )
    else:
        # 🔥 未指定数据源，按优先级查询
        source_priority = ["tushare", "multi_source", "akshare", "baostock"]
        b = None

        for src in source_priority:
            query_with_source = {"code": code6, "source": src}
            b = await db["stock_basic_info"].find_one(query_with_source, {"_id": 0})
            if b:
                logger.info(f"✅ 使用数据源: {src} 查询股票 {code6}")
                break

        # 如果所有数据源都没有，尝试不带 source 条件查询（兼容旧数据）
        if not b:
            b = await db["stock_basic_info"].find_one({"code": code6}, {"_id": 0})
            if b:
                logger.warning(f"⚠️ 使用旧数据（无 source 字段）: {code6}")

        if not b:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该股票的基础信息")

    # 2. 尝试从 stock_financial_data 获取最新财务指标
    # 🔥 按数据源优先级查询，而不是按时间戳，避免混用不同数据源的数据
    financial_data = None
    try:
        # 获取数据源优先级配置
        from app.core.unified_config import UnifiedConfigManager
        config = UnifiedConfigManager()
        data_source_configs = await config.get_data_source_configs_async()

        # 提取启用的数据源，按优先级排序
        enabled_sources = [
            ds.type.lower() for ds in data_source_configs
            if ds.enabled and ds.type.lower() in ['tushare', 'akshare', 'baostock']
        ]

        if not enabled_sources:
            enabled_sources = ['tushare', 'akshare', 'baostock']

        # 按数据源优先级查询财务数据
        for data_source in enabled_sources:
            financial_data = await db["stock_financial_data"].find_one(
                {"$or": [{"symbol": code6}, {"code": code6}], "data_source": data_source},
                {"_id": 0},
                sort=[("report_period", -1)]  # 按报告期降序，获取该数据源的最新数据
            )
            if financial_data:
                logger.info(f"✅ 使用数据源 {data_source} 的财务数据 (报告期: {financial_data.get('report_period')})")
                break

        if not financial_data:
            logger.warning(f"⚠️ 未找到 {code6} 的财务数据")
    except Exception as e:
        logger.error(f"获取财务数据失败: {e}")

    # 3. 获取实时PE/PB（优先使用实时计算）
    try:
        from tradingagents.dataflows.realtime_metrics import get_pe_pb_with_fallback
    except ImportError:
        logger.warning("tradingagents.dataflows.realtime_metrics 不可用，跳过实时PE/PB计算")
        def get_pe_pb_with_fallback(*args, **kwargs):
            return {}
    import asyncio

    # 在线程池中执行同步的实时计算
    realtime_metrics_raw = await asyncio.to_thread(
        get_pe_pb_with_fallback,
        code6,
        db.client
    )
    realtime_metrics = realtime_metrics_raw if isinstance(realtime_metrics_raw, dict) else {}

    # 4. 构建返回数据
    # 🔥 优先使用实时市值，降级到 stock_basic_info 的静态市值
    realtime_market_cap = realtime_metrics.get("market_cap")  # 实时市值（亿元）
    total_mv = realtime_market_cap if realtime_market_cap else b.get("total_mv")

    data = {
        "code": code6,
        "name": b.get("name"),
        "industry": b.get("industry"),  # 行业（如：银行、软件服务）
        "market": b.get("market"),      # 交易所（如：主板、创业板）

        # 板块信息：使用 market 字段（主板/创业板/科创板/北交所等）
        "sector": b.get("market"),

        # 估值指标（优先使用实时计算，降级到 stock_basic_info）
        "pe": realtime_metrics.get("pe") or b.get("pe"),
        "pb": realtime_metrics.get("pb") or b.get("pb"),
        "pe_ttm": realtime_metrics.get("pe_ttm") or b.get("pe_ttm"),
        "pb_mrq": realtime_metrics.get("pb_mrq") or b.get("pb_mrq"),

        # 🔥 市销率（PS）- 动态计算（使用实时市值）
        "ps": None,
        "ps_ttm": None,

        # PE/PB 数据来源标识
        "pe_source": realtime_metrics.get("source", "unknown"),
        "pe_is_realtime": realtime_metrics.get("is_realtime", False),
        "pe_updated_at": realtime_metrics.get("updated_at"),

        # ROE（优先从 stock_financial_data 获取，其次从 stock_basic_info）
        "roe": None,

        # 负债率（从 stock_financial_data 获取）
        "debt_ratio": None,

        # 市值：优先使用实时市值，降级到静态市值
        "total_mv": total_mv,
        "circ_mv": b.get("circ_mv"),

        # 🔥 市值来源标识
        "mv_is_realtime": bool(realtime_market_cap),

        # 交易指标（可能为空）
        "turnover_rate": b.get("turnover_rate"),
        "volume_ratio": b.get("volume_ratio"),

        "updated_at": b.get("updated_at"),
    }

    # 5. 从财务数据中提取 ROE、负债率和计算 PS
    if financial_data:
        # ROE（净资产收益率）
        if financial_data.get("financial_indicators"):
            indicators = financial_data["financial_indicators"]
            data["roe"] = indicators.get("roe")
            data["debt_ratio"] = indicators.get("debt_to_assets")

        # 如果 financial_indicators 中没有，尝试从顶层字段获取
        if data["roe"] is None:
            data["roe"] = financial_data.get("roe")
        if data["debt_ratio"] is None:
            data["debt_ratio"] = financial_data.get("debt_to_assets")

        # 🔥 动态计算 PS（市销率）- 使用实时市值
        # 优先使用 TTM 营业收入，如果没有则使用单期营业收入
        revenue_ttm = financial_data.get("revenue_ttm")
        revenue = financial_data.get("revenue")
        revenue_for_ps = revenue_ttm if revenue_ttm and revenue_ttm > 0 else revenue

        if revenue_for_ps and revenue_for_ps > 0:
            # 🔥 使用实时市值（如果有），否则使用静态市值
            if total_mv and total_mv > 0:
                # 营业收入单位：元，需要转换为亿元
                revenue_yi = revenue_for_ps / 100000000
                ps_calculated = total_mv / revenue_yi
                data["ps"] = round(ps_calculated, 2)
                data["ps_ttm"] = round(ps_calculated, 2) if revenue_ttm else None

        # 🔥 提取更多财务指标（如果有的话）
        financial_detail = {}

        # 利润表指标
        financial_detail["revenue"] = financial_data.get("revenue")
        financial_detail["revenue_ttm"] = financial_data.get("revenue_ttm")
        financial_detail["net_profit"] = financial_data.get("net_profit")
        financial_detail["net_profit_ttm"] = financial_data.get("net_profit_ttm")
        financial_detail["gross_profit"] = financial_data.get("gross_profit")

        # 盈利能力
        financial_detail["gross_margin"] = financial_data.get("gross_margin")
        financial_detail["net_margin"] = financial_data.get("net_margin")
        financial_detail["roa"] = financial_data.get("roa")

        # 偿债能力
        financial_detail["current_ratio"] = financial_data.get("current_ratio")
        financial_detail["quick_ratio"] = financial_data.get("quick_ratio")

        # 每股指标
        financial_detail["eps"] = financial_data.get("eps")
        financial_detail["bps"] = financial_data.get("bps")

        # 增长率
        financial_detail["revenue_yoy"] = financial_data.get("revenue_yoy")
        financial_detail["net_profit_yoy"] = financial_data.get("net_profit_yoy")

        # 报告期信息
        financial_detail["report_period"] = financial_data.get("report_period")
        financial_detail["report_type"] = financial_data.get("report_type")
        financial_detail["data_source"] = financial_data.get("data_source")

        # 如果 financial_indicators 中有更多指标，也提取出来
        if financial_data.get("financial_indicators"):
            indicators = financial_data["financial_indicators"]
            for key in ["gross_margin", "net_margin", "roa", "current_ratio", "quick_ratio", "eps", "bps", "revenue_yoy", "net_profit_yoy"]:
                if financial_detail.get(key) is None and indicators.get(key) is not None:
                    financial_detail[key] = indicators.get(key)
            # 额外提取可能存在的其他指标
            for key in ["net_profit", "revenue", "gross_profit"]:
                if financial_detail.get(key) is None and indicators.get(key) is not None:
                    financial_detail[key] = indicators.get(key)

        data["financial_detail"] = financial_detail

    # 6. 如果财务数据中没有 ROE，使用 stock_basic_info 中的
    if data["roe"] is None:
        data["roe"] = b.get("roe")

    # 7. 🔥 数据约束验证：清理异常值，避免"离谱"数据影响用户体验
    try:
        from tradingagents.dataflows.data_validator import validate_stock_data
        validation_result = validate_stock_data(data, code6)
        data = validation_result["clean_data"]
        if validation_result["warnings"]:
            data["data_warnings"] = validation_result["warnings"]
            logger.info(f"📊 {code6} 数据验证: {validation_result['sanitized_count']}/{validation_result['total_fields']} 个字段被清理")
    except Exception as e:
        logger.warning(f"⚠️ 数据验证模块不可用，跳过验证: {e}")

    return ok(data)


@router.get("/{code}/kline", response_model=dict)
async def get_kline(
    code: str,
    period: str = "day",
    limit: int = 120,
    adj: str = "none",
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取K线数据（支持A股/港股/美股）

    period: day/week/month/5m/15m/30m/60m
    adj: none/qfq/hfq
    force_refresh: 是否强制刷新（跳过缓存）

    🔥 新增功能：当天实时K线数据
    - 交易时间内（09:30-15:00）：从 market_quotes 获取实时数据
    - 收盘后：检查历史数据是否有当天数据，没有则从 market_quotes 获取
    """
    import logging
    from datetime import datetime, timedelta, time as dtime
    from zoneinfo import ZoneInfo
    logger = logging.getLogger(__name__)

    valid_periods = {"day","week","month","5m","15m","30m","60m"}
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"不支持的period: {period}")

    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新服务
    if market in ['HK', 'US']:
        from app.services.foreign_stock_service import ForeignStockService

        db = get_mongo_db()  # 不需要 await，直接返回数据库对象
        service = ForeignStockService(db=db)

        try:
            kline_data = await service.get_kline(market, normalized_code, period, limit, force_refresh)
            return ok(data={
                'code': normalized_code,
                'period': period,
                'items': kline_data,
                'source': 'cache_or_api'
            })
        except Exception as e:
            logger.error(f"获取{market}股票{code}K线数据失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取K线数据失败: {str(e)}"
            )

    # A股：使用现有逻辑
    code_padded = normalized_code
    adj_norm = None if adj in (None, "none", "", "null") else adj
    items = None
    source = None

    # 周期映射：前端 -> MongoDB
    period_map = {
        "day": "daily",
        "week": "weekly",
        "month": "monthly",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "60min"
    }
    mongodb_period = period_map.get(period, "daily")

    # 获取当前时间（北京时间）
    from app.core.config import settings
    tz = ZoneInfo(settings.TIMEZONE)
    now = datetime.now(tz)
    today_str_yyyymmdd = now.strftime("%Y%m%d")  # 格式：20251028（用于查询）
    today_str_formatted = now.strftime("%Y-%m-%d")  # 格式：2025-10-28（用于返回）

    db = get_mongo_db()

    # 1. 优先从 MongoDB 缓存获取（支持多个集合）
    try:
        from tradingagents.dataflows.cache.mongodb_cache_adapter import get_mongodb_cache_adapter
        adapter = get_mongodb_cache_adapter()

        # 计算日期范围
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=limit * 2)).strftime("%Y-%m-%d")

        logger.info(f"🔍 尝试从 MongoDB 获取 K 线数据: {code_padded}, period={period} (MongoDB: {mongodb_period}), limit={limit}")
        df = adapter.get_historical_data(code_padded, start_date, end_date, period=mongodb_period)

        if df is not None and not df.empty:
            # 转换 DataFrame 为列表格式
            items = []
            for _, row in df.tail(limit).iterrows():
                items.append({
                    "time": str(row.get("trade_date", row.get("date", ""))),  # 前端期望 time 字段
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", row.get("vol", 0))),
                    "amount": float(row.get("amount", 0)) if "amount" in row else None,
                })
            source = "mongodb"
            logger.info(f"✅ 从 MongoDB 获取到 {len(items)} 条 K 线数据")
    except Exception as e:
        logger.warning(f"⚠️ MongoDB 缓存适配器获取 K 线失败: {e}")

    # 1.5 备用：直接从 stock_daily_quotes 查询（日线）
    if not items and period == "day":
        try:
            logger.info(f"🔍 尝试直接从 stock_daily_quotes 查询 K线: {code_padded}")
            coll = db["stock_daily_quotes"]
            query = {
                "$or": [{"code": code_padded}, {"symbol": code_padded}],
                "period": "daily"
            }
            cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
            records = list(cursor)

            if records:
                # 反转成正序
                records.reverse()
                items = []
                for rec in records:
                    items.append({
                        "time": str(rec.get("trade_date", rec.get("date", ""))),
                        "open": float(rec.get("open", 0) or 0),
                        "high": float(rec.get("high", 0) or 0),
                        "low": float(rec.get("low", 0) or 0),
                        "close": float(rec.get("close", 0) or 0),
                        "volume": float(rec.get("volume", 0) or 0),
                        "amount": float(rec.get("amount", 0) or 0) if rec.get("amount") is not None else None,
                    })
                source = "stock_daily_quotes"
                logger.info(f"✅ 从 stock_daily_quotes 获取到 {len(items)} 条 K线数据")
        except Exception as e:
            logger.warning(f"⚠️ 直接查询 stock_daily_quotes 失败: {e}")

    # 2. 如果 MongoDB 没有数据，降级到外部 API（带超时保护，缩短超时避免长时间等待）
    if not items:
        logger.info(f"📡 MongoDB 无数据，降级到外部 API")
        try:
            import asyncio
            from app.services.data_sources.manager import DataSourceManager

            mgr = DataSourceManager()
            # 缩短超时时从 10秒 改为 8秒，避免用户等待太久
            items, source = await asyncio.wait_for(
                asyncio.to_thread(mgr.get_kline_with_fallback, code_padded, period, limit, adj_norm),
                timeout=8.0
            )

            # 🔥 外部API获取成功后，保存到MongoDB缓存（不阻塞返回）
            if items and source:
                try:
                    adapter.save_historical_data(code_padded, mongodb_period, items, source)
                except Exception as save_err:
                    logger.warning(f"⚠️ 保存K线到MongoDB缓存失败（不影响返回）: {save_err}")

        except asyncio.TimeoutError:
            logger.warning(f"⚠️ 外部 API 获取 K 线超时（8秒），使用缓存数据或返回空")
        except Exception as e:
            logger.warning(f"⚠️ 外部 API 获取 K 线失败: {e}")

    # 🔥 3. 检查是否需要添加当天实时数据（仅针对日线）
    if period == "day" and items:
        try:
            # 检查历史数据中是否已有当天的数据（支持两种日期格式）
            has_today_data = any(
                item.get("time") in [today_str_yyyymmdd, today_str_formatted]
                for item in items
            )

            # 判断是否在交易时间内或收盘后缓冲期
            current_time = now.time()
            is_weekday = now.weekday() < 5  # 周一到周五

            # 交易时间：9:30-11:30, 13:00-15:00
            # 收盘后缓冲期：15:00-15:30（确保获取到收盘价）
            is_trading_time = (
                is_weekday and (
                    (dtime(9, 30) <= current_time <= dtime(11, 30)) or
                    (dtime(13, 0) <= current_time <= dtime(15, 30))
                )
            )

            # 🔥 只在交易时间或收盘后缓冲期内才添加实时数据
            # 非交易日（周末、节假日）不添加实时数据
            should_fetch_realtime = is_trading_time

            if should_fetch_realtime:
                logger.info(f"🔥 尝试从 market_quotes 获取当天实时数据: {code_padded} (交易时间: {is_trading_time}, 已有当天数据: {has_today_data})")

                db = get_mongo_db()
                market_quotes_coll = db["market_quotes"]

                # 查询当天的实时行情
                realtime_quote = await market_quotes_coll.find_one({"code": code_padded})

                if realtime_quote:
                    # 🔥 构造当天的K线数据（使用统一的日期格式 YYYY-MM-DD）
                    today_kline = {
                        "time": today_str_formatted,  # 🔥 使用 YYYY-MM-DD 格式，与历史数据保持一致
                        "open": float(realtime_quote.get("open", 0)),
                        "high": float(realtime_quote.get("high", 0)),
                        "low": float(realtime_quote.get("low", 0)),
                        "close": float(realtime_quote.get("close", 0)),
                        "volume": float(realtime_quote.get("volume", 0)),
                        "amount": float(realtime_quote.get("amount", 0)),
                    }

                    # 如果历史数据中已有当天数据，替换；否则追加
                    if has_today_data:
                        # 替换最后一条数据（假设最后一条是当天的）
                        items[-1] = today_kline
                        logger.info(f"✅ 替换当天K线数据: {code_padded}")
                    else:
                        # 追加到末尾
                        items.append(today_kline)
                        logger.info(f"✅ 追加当天K线数据: {code_padded}")

                    source = f"{source}+market_quotes"
                else:
                    logger.warning(f"⚠️ market_quotes 中未找到当天数据: {code_padded}")
        except Exception as e:
            logger.warning(f"⚠️ 获取当天实时数据失败（忽略）: {e}")

    data = {
        "code": code_padded,
        "period": period,
        "limit": limit,
        "adj": adj if adj else "none",
        "source": source,
        "items": items or []
    }
    return ok(data)


@router.get("/{code}/news", response_model=dict)
async def get_news(code: str, days: int = 30, limit: int = 50, include_announcements: bool = True, current_user: dict = Depends(get_current_user)):
    """获取新闻与公告（支持A股、港股、美股）"""
    from app.services.foreign_stock_service import ForeignStockService
    from app.services.news_data_service import get_news_data_service, NewsQueryParams

    # 检测股票类型
    market, normalized_code = _detect_market_and_code(code)

    if market == 'US':
        # 美股：使用 ForeignStockService
        service = ForeignStockService()
        result = await service.get_us_news(normalized_code, days=days, limit=limit)
        return ok(result)
    elif market == 'HK':
        # 港股：暂时返回空数据（TODO: 实现港股新闻）
        data = {
            "code": normalized_code,
            "days": days,
            "limit": limit,
            "source": "none",
            "items": []
        }
        return ok(data)
    else:
        # A股：直接调用同步服务的查询方法（包含智能回退逻辑）
        try:
            logger.info(f"=" * 80)
            logger.info(f"📰 开始获取新闻: code={code}, normalized_code={normalized_code}, days={days}, limit={limit}")

            # 直接使用 news_data 路由的查询逻辑
            from app.services.news_data_service import get_news_data_service, NewsQueryParams
            from datetime import datetime, timedelta
            from app.worker.akshare_sync_service import get_akshare_sync_service

            service = await get_news_data_service()
            sync_service = await get_akshare_sync_service()

            # 计算时间范围
            hours_back = days * 24

            # 🔥 不设置 start_time 限制，直接查询最新的 N 条新闻
            # 因为数据库中的新闻可能不是最近几天的，而是历史数据
            params = NewsQueryParams(
                symbol=normalized_code,
                limit=limit,
                sort_by="publish_time",
                sort_order=-1
            )

            logger.info(f"🔍 查询参数: symbol={params.symbol}, limit={params.limit} (不限制时间范围)")

            # 1. 先从数据库查询
            logger.info(f"📊 步骤1: 从数据库查询新闻...")
            news_list = await service.query_news(params)
            logger.info(f"📊 数据库查询结果: 返回 {len(news_list)} 条新闻")

            # 🔥 检查数据库中是否有真正的新闻（非公告）类型数据
            has_real_news = any(
                news.get("type", "news") == "news" and "公告" not in str(news.get("title", ""))
                for news in news_list
            )

            data_source = "database"

            # 2. 如果数据库没有新闻类型数据，尝试从多个数据源实时获取
            if not has_real_news:
                logger.info(f"⚠️ 数据库无新闻类型数据，尝试从多数据源实时获取: {normalized_code}")
                try:
                    # 🔥 直接调用AKShare适配器获取新闻（不依赖同步服务）
                    from app.services.data_sources.akshare_adapter import AKShareAdapter
                    adapter = AKShareAdapter()
                    logger.info(f"📡 步骤2: 从AKShare实时获取新闻...")
                    akshare_items = adapter.get_news(normalized_code, days=days, limit=limit, include_announcements=False)

                    if akshare_items:
                        logger.info(f"✅ AKShare获取到 {len(akshare_items)} 条新闻")
                        # 转换为数据库格式并保存（异步保存，不阻塞返回）
                        try:
                            news_docs = []
                            for item in akshare_items:
                                news_docs.append({
                                    "symbol": normalized_code,
                                    "title": item.get("title", ""),
                                    "source": item.get("source", ""),
                                    "publish_time": item.get("time", ""),
                                    "url": item.get("url", ""),
                                    "type": item.get("type", "news"),
                                    "content": item.get("content", ""),
                                    "summary": item.get("summary", ""),
                                    "data_source": "akshare",
                                    "created_at": datetime.now(),
                                    "updated_at": datetime.now()
                                })

                            # 异步保存到数据库（使用replace_one with upsert）
                            db = get_mongo_db()
                            for doc in news_docs:
                                try:
                                    await db["stock_news"].replace_one(
                                        {"url": doc["url"], "title": doc["title"]},
                                        doc,
                                        upsert=True
                                    )
                                except Exception as save_err:
                                    logger.warning(f"保存新闻失败: {save_err}")

                            logger.info(f"✅ 已保存 {len(news_docs)} 条新闻到数据库")
                        except Exception as save_err:
                            logger.warning(f"保存新闻到数据库失败: {save_err}")

                        # 合并AKShare返回的数据（保留已有的数据库数据）
                        akshare_news_list = [{"publish_time": item.get("time", ""), "title": item.get("title", ""),
                                     "source": item.get("source", ""), "url": item.get("url", ""),
                                     "type": item.get("type", "news"), "content": item.get("content", ""),
                                     "summary": item.get("summary", "")} for item in akshare_items]

                        # 🔥 如果数据库有公告数据，保留；AKShare的新闻数据追加
                        if news_list and not has_real_news:
                            # 保留数据库的公告，追加AKShare的新闻
                            news_list = akshare_news_list + news_list
                        else:
                            news_list = akshare_news_list
                        data_source = "akshare_realtime"
                    else:
                        logger.warning(f"⚠️ AKShare未获取到新闻数据，尝试其他数据源")
                        # 🔥 尝试从其他数据源获取（如同花顺、东方财富等）
                        try:
                            extra_news = await _fetch_news_from_multiple_sources(normalized_code, days, limit)
                            if extra_news:
                                logger.info(f"✅ 从其他数据源获取到 {len(extra_news)} 条新闻")
                                news_list = extra_news + news_list
                                data_source = "multi_source"
                        except Exception as e2:
                            logger.warning(f"⚠️ 其他数据源获取新闻失败: {e2}")
                except Exception as e:
                    logger.error(f"❌ AKShare获取新闻失败: {e}", exc_info=True)

            # 转换为旧格式（兼容前端）
            logger.info(f"🔄 步骤4: 转换数据格式...")
            items = []
            for news in news_list:
                # 🔥 将 datetime 对象转换为 ISO 字符串
                publish_time = news.get("publish_time", "")
                if isinstance(publish_time, datetime):
                    publish_time = publish_time.isoformat()

                # 🔥 根据实际类型设置 type（公告 vs 新闻）
                news_type = news.get("type", "news")
                if news_type == "announcement":
                    item_type = "announcement"
                elif "notice" in str(news.get("title", "")).lower() or "公告" in str(news.get("title", "")):
                    item_type = "announcement"
                else:
                    item_type = "news"

                items.append({
                    "title": news.get("title", ""),
                    "source": news.get("source", ""),
                    "time": publish_time,
                    "url": news.get("url", ""),
                    "type": item_type,
                    "content": news.get("content", ""),
                    "summary": news.get("summary", "")
                })

            logger.info(f"✅ 转换完成: {len(items)} 条新闻")

            # 🔥 补充公告数据（从东财实时获取，与 filings 页面一致）
            if include_announcements:
                try:
                    logger.info(f"📡 步骤5: 获取公告数据...")
                    from app.services.vibe_astock import announcements
                    anns = announcements(normalized_code, limit)
                    for ann in anns:
                        items.append({
                            "title": ann.get("title", ""),
                            "source": ann.get("source", "") or "东方财富",
                            "time": ann.get("date", ""),
                            "url": ann.get("url", ""),
                            "type": "announcement",
                            "content": "",
                            "summary": ""
                        })
                    logger.info(f"📡 获取公告完成: {len(anns)} 条公告")
                except Exception as e:
                    logger.error(f"❌ 获取公告失败: {e}")

            # 按时间排序（最新在前），同时间的公告优先显示
            items.sort(key=lambda x: (x.get("time", ""), x.get("type") != "announcement"), reverse=True)
            # 截断到 limit 限制
            items = items[:limit]

            data = {
                "code": normalized_code,
                "days": days,
                "limit": limit,
                "include_announcements": include_announcements,
                "source": data_source,
                "items": items
            }

            logger.info(f"📤 最终返回: source={data_source}, items_count={len(items)}")
            logger.info(f"=" * 80)
            return ok(data)

        except Exception as e:
            logger.error(f"❌ 获取新闻失败: {e}", exc_info=True)
            data = {
                "code": normalized_code,
                "days": days,
                "limit": limit,
                "include_announcements": include_announcements,
                "source": None,
                "items": []
            }
            return ok(data)


@router.get("/{code}/sector-info", response_model=dict)
async def get_sector_info(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """
    获取股票所属板块信息及同板块股票表现

    返回：
    - sector_name: 所属板块名称
    - sector_stocks: 同板块股票列表（含涨跌幅）
    - sector_avg_change: 板块平均涨跌幅
    - sector_rank: 该股票在板块中的涨跌幅排名
    """
    market, normalized_code = _detect_market_and_code(code)

    if market != 'CN':
        return ok(data={"code": normalized_code, "sector_name": None, "sector_stocks": [], "message": "仅支持A股板块分析"})

    code6 = str(normalized_code).zfill(6)
    db = get_mongo_db()
    sector_name = None
    sector_stocks = []
    stock_codes = []  # 同行业全部股票代码（用于统计板块总规模）
    avg_change = 0
    rank = None

    # 1. 优先从 MongoDB stock_basic_info 获取行业信息
    # ⚠️ 同一只股票可能在多个数据源（akshare/baostock/tushare）中各有一条记录，
    #    其中 akshare 源的 industry 字段可能为空字符串。find_one 默认返回第一条，
    #    可能命中空 industry 记录，导致 sector_name 一直为 None。
    #    修复：显式过滤掉空 industry 记录，并选择同行业股票数量最多的行业分类。
    try:
        candidates = await db["stock_basic_info"].find(
            {
                "$or": [{"code": code6}, {"symbol": code6}],
                "industry": {"$exists": True, "$nin": ["", None]}
            },
            {"_id": 0, "industry": 1, "name": 1, "source": 1}
        ).to_list(length=10)

        if candidates:
            # 去重收集所有非空行业名称
            industries = []
            seen = set()
            for c in candidates:
                ind = c.get("industry")
                if ind and ind not in seen:
                    seen.add(ind)
                    industries.append(str(ind))

            if industries:
                if len(industries) == 1:
                    sector_name = industries[0]
                else:
                    # 多个数据源给出不同行业名称时，选择同行业股票数量最多的行业
                    # （通常对应更准确的板块划分，如"专用设备制造业"360只 vs "专用机械"292只）
                    best_industry = None
                    best_count = 0
                    for ind in industries:
                        try:
                            cnt = await db["stock_basic_info"].count_documents(
                                {"industry": ind}
                            )
                            if cnt > best_count:
                                best_count = cnt
                                best_industry = ind
                        except Exception:
                            pass
                    sector_name = best_industry or industries[0]
                logger.info(f"✅ 从 stock_basic_info 获取行业: {code6} -> {sector_name} (候选: {industries})")
    except Exception as e:
        logger.warning(f"从 stock_basic_info 获取行业失败: {e}")

    # 2. 如果MongoDB没有，尝试AKShare
    if not sector_name:
        try:
            import akshare as ak
            import asyncio
            df_sector = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_individual_info_em, symbol=code6),
                timeout=5.0
            )
            if df_sector is not None and not df_sector.empty:
                for _, row in df_sector.iterrows():
                    item_name = str(row.get('item', ''))
                    if '行业' in item_name:
                        sector_name = str(row.get('value', ''))
                        break
            logger.info(f"✅ 从 AKShare 获取行业: {code6} -> {sector_name}")
        except Exception as e:
            logger.warning(f"从 AKShare 获取个股板块信息失败: {e}")

    # 2.5 如果AKShare也不可用，尝试东方财富API
    if not sector_name:
        try:
            import httpx
            # 东方财富个股信息接口
            market_code = "1" if code6.startswith('6') else "0"
            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market_code}.{code6}&fields=f127"  # f127=行业
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and data.get("data") and data["data"].get("f127"):
                        sector_name = str(data["data"]["f127"])
                        logger.info(f"✅ 从东方财富获取行业: {code6} -> {sector_name}")
        except Exception as e:
            logger.warning(f"从东方财富获取行业信息失败: {e}")

    # 3. 如果有行业名称，获取同行业股票表现
    if sector_name:
        # 3.1 优先从 MongoDB 获取同行业股票列表
        try:
            # 获取全部同行业股票（不限制数量，以便计算总板块规模和目标股票排名）
            industry_stocks = await db["stock_basic_info"].find(
                {"industry": sector_name},
                {"_id": 0, "code": 1, "symbol": 1, "name": 1}
            ).to_list(length=1000)

            if industry_stocks:
                # 收集股票代码（去重）
                stock_codes = []
                code_to_name = {}
                seen_codes = set()
                for s in industry_stocks:
                    sc = s.get("code") or s.get("symbol")
                    if sc and sc not in seen_codes:
                        seen_codes.add(sc)
                        stock_codes.append(sc)
                        code_to_name[sc] = s.get("name", "")

                # 兜底：确保目标股票的名称已加载（可能因数据源差异未出现在同行业列表中）
                if code6 not in code_to_name:
                    target_info = await db["stock_basic_info"].find_one(
                        {"$or": [{"code": code6}, {"symbol": code6}], "name": {"$exists": True, "$ne": ""}},
                        {"_id": 0, "name": 1}
                    )
                    if target_info and target_info.get("name"):
                        code_to_name[code6] = target_info["name"]
                        if code6 not in stock_codes:
                            stock_codes.append(code6)
                    else:
                        code_to_name[code6] = ""
                        if code6 not in stock_codes:
                            stock_codes.append(code6)

                # ⚠️ market_quotes 存放的是当日实时行情（含 pct_chg），是最鲜活的数据源；
                #    stock_daily_quotes 历史K线数据可能较为陈旧（trade_date 停留在很久以前），
                #    且 pct_chg/pre_close 字段可能为 null。
                #    因此优先从 market_quotes 构建板块股票涨跌幅，避免出现空板块。
                rt_quotes = await db["market_quotes"].find(
                    {"code": {"$in": stock_codes}},
                    {"_id": 0, "code": 1, "close": 1, "pct_chg": 1, "pre_close": 1, "trade_date": 1}
                ).to_list(length=300)

                rt_map = {}
                rt_trade_date = None
                for q in rt_quotes:
                    sc = q.get("code", "")
                    rt_map[sc] = q
                    if q.get("trade_date"):
                        rt_trade_date = q.get("trade_date")

                # 构建板块股票列表（以 market_quotes 为主，缺失的用 stock_daily_quotes 兜底）
                # ⚠️ 确保目标股票本身一定在展示列表中，否则无法计算其板块排名
                display_codes = list(stock_codes[:29])
                if code6 not in display_codes and code6 in stock_codes:
                    display_codes.append(code6)
                elif code6 not in display_codes:
                    display_codes.append(code6)

                sector_stocks = []
                for sc in display_codes:
                    rt = rt_map.get(sc)
                    if rt and rt.get("close") is not None:
                        pct = rt.get("pct_chg")
                        close = rt.get("close")
                        pre = rt.get("pre_close")
                        # 如果 pct_chg 缺失但有昨收价，则计算
                        if pct is None and close and pre and pre > 0:
                            pct = round((close / pre - 1) * 100, 2)
                        sector_stocks.append({
                            "code": sc,
                            "name": code_to_name.get(sc, ""),
                            "change_pct": float(pct) if pct is not None else 0,
                            "price": float(close) if close is not None else 0,
                        })
                    else:
                        # market_quotes 缺失，尝试从 stock_daily_quotes 兜底
                        dq = await db["stock_daily_quotes"].find_one(
                            {"code": sc, "period": "daily"},
                            {"_id": 0, "close": 1, "pct_chg": 1, "pre_close": 1},
                            sort=[("trade_date", -1)]
                        )
                        if dq and dq.get("close") is not None:
                            pct = dq.get("pct_chg")
                            close = dq.get("close")
                            pre = dq.get("pre_close")
                            if pct is None and close and pre and pre > 0:
                                pct = round((close / pre - 1) * 100, 2)
                            sector_stocks.append({
                                "code": sc,
                                "name": code_to_name.get(sc, ""),
                                "change_pct": float(pct) if pct is not None else 0,
                                "price": float(close) if close is not None else 0,
                            })
                        else:
                            sector_stocks.append({
                                "code": sc,
                                "name": code_to_name.get(sc, ""),
                                "change_pct": 0,
                                "price": 0,
                            })

                # 按涨跌幅排序
                sector_stocks.sort(key=lambda x: x["change_pct"], reverse=True)

                # 计算平均涨跌幅
                valid_changes = [s["change_pct"] for s in sector_stocks if s["change_pct"] is not None]
                if valid_changes:
                    avg_change = round(sum(valid_changes) / len(valid_changes), 2)

                # 计算排名
                for i, s in enumerate(sector_stocks):
                    if s["code"] == code6:
                        rank = i + 1
                        break

                logger.info(f"✅ 从 MongoDB(market_quotes) 获取板块数据: {sector_name}, {len(sector_stocks)} 只股票, trade_date={rt_trade_date}")

        except Exception as e:
            logger.warning(f"从 MongoDB 获取板块股票数据失败: {e}")

        # 3.2 如果MongoDB没有数据，尝试AKShare
        if not sector_stocks:
            try:
                import akshare as ak
                import asyncio
                df_industry = await asyncio.wait_for(
                    asyncio.to_thread(ak.stock_board_industry_cons_em, symbol=sector_name),
                    timeout=8.0
                )
                if df_industry is not None and not df_industry.empty:
                    sector_stocks = []
                    for _, row in df_industry.head(20).iterrows():
                        stock_code = str(row.get('代码', ''))
                        stock_name = str(row.get('名称', ''))
                        change_pct = float(row.get('涨跌幅', 0) or 0)
                        sector_stocks.append({
                            "code": stock_code,
                            "name": stock_name,
                            "change_pct": change_pct,
                            "price": float(row.get('最新价', 0) or 0),
                        })

                    if sector_stocks:
                        avg_change = round(sum(s["change_pct"] for s in sector_stocks) / len(sector_stocks), 2)
                        sorted_stocks = sorted(sector_stocks, key=lambda x: x["change_pct"], reverse=True)
                        rank = next((i + 1 for i, s in enumerate(sorted_stocks) if s["code"] == code6), None)
                    logger.info(f"✅ 从 AKShare 获取板块成分股: {len(sector_stocks)} 只")
            except Exception as e:
                logger.warning(f"从 AKShare 获取板块成分股失败: {e}")

    # 4. 从 market_quotes 获取实时涨跌幅补充（如果有数据的话）
    if sector_stocks:
        try:
            realtime_quotes = await db["market_quotes"].find(
                {"code": {"$in": [s["code"] for s in sector_stocks]}},
                {"_id": 0, "code": 1, "close": 1, "pct_chg": 1}
            ).to_list(length=50)
            if realtime_quotes:
                rt_map = {q["code"]: q for q in realtime_quotes}
                for s in sector_stocks:
                    if s["code"] in rt_map and rt_map[s["code"]].get("pct_chg") is not None:
                        s["change_pct"] = float(rt_map[s["code"]]["pct_chg"])
                        if rt_map[s["code"]].get("close"):
                            s["price"] = float(rt_map[s["code"]]["close"])
                # 重新排序和计算
                sector_stocks.sort(key=lambda x: x["change_pct"], reverse=True)
                avg_change = round(sum(s["change_pct"] for s in sector_stocks) / len(sector_stocks), 2)
                for i, s in enumerate(sector_stocks):
                    if s["code"] == code6:
                        rank = i + 1
                        break
                logger.info(f"✅ 已用实时行情更新板块数据")
        except Exception as e:
            logger.warning(f"更新实时行情到板块数据失败: {e}")

    data = {
        "code": normalized_code,
        "sector_name": sector_name,
        "sector_stocks": sector_stocks[:20],
        "sector_avg_change": round(avg_change, 2) if sector_stocks else 0,
        "sector_rank": rank,
        "total_in_sector": len(stock_codes) if sector_name else 0,
        "displayed_count": len(sector_stocks),
        "data_source": "mongodb" if sector_stocks else "none"
    }
    return ok(data=data)


@router.get("/{code}/money-flow", response_model=dict)
async def get_money_flow(
    code: str,
    days: int = Query(5, description="查询天数"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取主力资金流向数据

    返回：
    - main_net_inflow: 主力净流入金额（元）
    - main_net_inflow_pct: 主力净流入占比
    - super_large_net: 超大单净流入
    - large_net: 大单净流入
    - medium_net: 中单净流入
    - small_net: 小单净流入
    - history: 近N天资金流向历史

    数据策略：
    - 仅返回 AKShare 真实资金流向数据
    - AKShare 不可用时明确返回 data_source="unavailable"，不再用估算模型伪装
    - 交易决策类数据绝不能用模拟值
    """
    market, normalized_code = _detect_market_and_code(code)

    if market != 'CN':
        return ok(data={"code": normalized_code, "message": "仅支持A股资金流向分析"})

    code6 = str(normalized_code).zfill(6)
    realtime_data = {}
    history = []
    trend = "unknown"
    data_source = "none"
    error_message = None

    # 数据源优先级：Tushare moneyflow（付费用户稳定） → AKShare（容器内常被东方财富风控）
    # Tushare 返回金额单位为万元，统一 ×10000 转为元，与 AKShare 口径一致
    tushare_ok = False
    try:
        import asyncio
        import tushare as ts

        token = os.getenv('TUSHARE_TOKEN', '').strip().strip('"').strip("'")
        if token:
            ts.set_token(token)
            pro = ts.pro_api()

            # ts_code 映射：6/9开头=SH，8开头=BJ，其余=SZ
            if code6.startswith(('6', '9')):
                ts_code = f"{code6}.SH"
            elif code6.startswith('8'):
                ts_code = f"{code6}.BJ"
            else:
                ts_code = f"{code6}.SZ"

            df_ts = await asyncio.wait_for(
                asyncio.to_thread(pro.moneyflow, ts_code=ts_code, limit=days + 2),
                timeout=8.0
            )
            if df_ts is not None and not df_ts.empty:
                # 按交易日期升序排序
                df_ts = df_ts.sort_values('trade_date').reset_index(drop=True)
                df_hist = df_ts.tail(days)

                def _safe_float(v):
                    try:
                        return float(v) if v is not None else 0.0
                    except Exception:
                        return 0.0

                def _row_to_item(row):
                    # Tushare moneyflow 字段单位为万元，统一转元
                    buy_sm = _safe_float(row.get('buy_sm_amount'))
                    sell_sm = _safe_float(row.get('sell_sm_amount'))
                    buy_md = _safe_float(row.get('buy_md_amount'))
                    sell_md = _safe_float(row.get('sell_md_amount'))
                    buy_lg = _safe_float(row.get('buy_lg_amount'))
                    sell_lg = _safe_float(row.get('sell_lg_amount'))
                    buy_elg = _safe_float(row.get('buy_elg_amount'))
                    sell_elg = _safe_float(row.get('sell_elg_amount'))

                    super_large_net = (buy_elg - sell_elg) * 10000  # 万元 → 元
                    large_net = (buy_lg - sell_lg) * 10000
                    medium_net = (buy_md - sell_md) * 10000
                    small_net = (buy_sm - sell_sm) * 10000
                    main_net_inflow = super_large_net + large_net  # 主力 = 超大单 + 大单

                    # 净占比 = 主力净额 / 总成交额 × 100
                    total_amount = (buy_sm + sell_sm + buy_md + sell_md + buy_lg + sell_lg + buy_elg + sell_elg) * 10000
                    main_net_inflow_pct = round(main_net_inflow / total_amount * 100, 2) if total_amount > 0 else 0.0

                    return {
                        "super_large_net": round(super_large_net, 2),
                        "large_net": round(large_net, 2),
                        "medium_net": round(medium_net, 2),
                        "small_net": round(small_net, 2),
                        "main_net_inflow": round(main_net_inflow, 2),
                        "main_net_inflow_pct": main_net_inflow_pct,
                    }

                latest = df_ts.iloc[-1]
                latest_item = _row_to_item(latest)
                realtime_data = {
                    "date": str(latest.get('trade_date', '')),
                    "change_pct": 0.0,  # Tushare moneyflow 不含涨跌幅，前端从行情区获取
                    **latest_item,
                    "is_estimated": False,
                }

                for _, row in df_hist.iterrows():
                    item = _row_to_item(row)
                    history.append({
                        "date": str(row.get('trade_date', '')),
                        **item,
                    })

                data_source = "tushare"
                tushare_ok = True
                logger.info(f"✅ 从 Tushare moneyflow 获取资金流向: {code6}, {len(history)} 条")
            else:
                logger.warning(f"Tushare moneyflow 返回空数据: {code6}")
    except asyncio.TimeoutError:
        logger.warning(f"Tushare moneyflow 超时: {code6}")
    except Exception as e:
        logger.warning(f"Tushare moneyflow 失败: {code6}, 错误: {e}")
        err_str = str(e)
        if "权限" in err_str or "permission" in err_str:
            error_message = f"Tushare moneyflow 无权限: {err_str}"

    # Tushare 失败时尝试 AKShare 备选（容器内常被东方财富风控，但保留作为非容器环境兜底）
    if not tushare_ok:
        try:
            import akshare as ak
            import asyncio

            # 修正 market 参数映射：6开头=sh，0/3开头=sz，8/4开头=bj（北交所）
            if code6.startswith('6'):
                ak_market = "sh"
            elif code6.startswith(('8', '4')):
                ak_market = "bj"
            else:
                ak_market = "sz"

            df_realtime = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_individual_fund_flow, stock=code6, market=ak_market),
                timeout=8.0
            )
            if df_realtime is not None and not df_realtime.empty:
                latest = df_realtime.tail(1).iloc[0]
                realtime_data = {
                    "date": str(latest.get('日期', '')),
                    "close": float(latest.get('收盘价', 0) or 0),
                    "change_pct": float(latest.get('涨跌幅', 0) or 0),
                    "main_net_inflow": float(latest.get('主力净流入-净额', 0) or 0),
                    "main_net_inflow_pct": float(latest.get('主力净流入-净占比', 0) or 0),
                    "super_large_net": float(latest.get('超大单净流入-净额', 0) or 0),
                    "super_large_pct": float(latest.get('超大单净流入-净占比', 0) or 0),
                    "large_net": float(latest.get('大单净流入-净额', 0) or 0),
                    "large_pct": float(latest.get('大单净流入-净占比', 0) or 0),
                    "medium_net": float(latest.get('中单净流入-净额', 0) or 0),
                    "medium_pct": float(latest.get('中单净流入-净占比', 0) or 0),
                    "small_net": float(latest.get('小单净流入-净额', 0) or 0),
                    "small_pct": float(latest.get('小单净流入-净占比', 0) or 0),
                    "is_estimated": False,
                }

                # 历史数据
                df_hist = df_realtime.tail(days)
                for _, row in df_hist.iterrows():
                    history.append({
                        "date": str(row.get('日期', '')),
                        "change_pct": float(row.get('涨跌幅', 0) or 0),
                        "main_net_inflow": float(row.get('主力净流入-净额', 0) or 0),
                        "main_net_inflow_pct": float(row.get('主力净流入-净占比', 0) or 0),
                    })

                data_source = "akshare"
                logger.info(f"✅ 从 AKShare 获取资金流向: {code6}")
            else:
                if not error_message:
                    error_message = "Tushare 与 AKShare 均返回空数据"
                data_source = "unavailable"
        except asyncio.TimeoutError:
            if not error_message:
                error_message = "Tushare 失败且 AKShare 接口超时"
            data_source = "unavailable"
            logger.warning(f"AKShare 获取资金流向超时: {code6}")
        except Exception as e:
            if not error_message:
                error_message = f"Tushare 失败且 AKShare 异常: {str(e)}"
            data_source = "unavailable"
            logger.warning(f"AKShare 获取资金流向失败: {code6}, 错误: {e}")

    # 判断资金趋势（仅基于真实数据）
    if history:
        recent_inflows = [h["main_net_inflow"] for h in history[-3:]]
        positive_days = sum(1 for v in recent_inflows if v > 0)
        if positive_days >= 2:
            trend = "inflow"
        elif positive_days <= 1:
            trend = "outflow"
        else:
            trend = "balanced"

    data = {
        "code": normalized_code,
        "realtime": realtime_data,
        "history": history,
        "trend": trend,
        "days": days,
        "data_source": data_source,
        "is_estimated": False,  # 不再返回估算数据
    }
    # 当数据不可用时，附带错误信息供前端展示
    if data_source == "unavailable":
        data["error_message"] = error_message or "资金流向数据暂时不可用，请稍后重试"
        logger.info(f"⚠️ 资金流向数据不可用: {code6}, 原因: {error_message}")

    return ok(data=data)


@router.get("/{code}/risk-analysis", response_model=dict)
async def get_risk_analysis(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """
    获取股票风险分析数据（来自通达信）

    仅支持A股，返回风险评分、风险分类、风险项等信息。

    参数：
    - code: 股票代码

    返回：
    - total: 总检查项数
    - num: 风险项数
    - name: 股票名称
    - score: 风险评分（满分100）
    - categories: 风险分类列表
    """
    import httpx

    market, normalized_code = _detect_market_and_code(code)

    if market != 'CN':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="风险分析仅支持A股"
        )

    try:
        url = f"http://page1.tdx.com.cn:7615/site/pcwebcall_static/bxb/json/{normalized_code}.json"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            raw_data = response.json()

        total = raw_data.get("total", 0)
        num = raw_data.get("num", 0)
        name = raw_data.get("name", "")
        raw_categories = raw_data.get("data", [])

        score = max(0, min(100, 100 - num * 5)) if total > 0 else 0

        categories = []
        for cat in raw_categories:
            cat_name = cat.get("name", "")
            rows = cat.get("rows", [])

            risk_items = []
            safe_items = []

            for row in rows:
                trig_yy = row.get("trigyy") or ""
                trig_yy = trig_yy.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")

                item = {
                    "id": row.get("id"),
                    "name": row.get("lx", ""),
                    "trig": row.get("trig", 0) == 1,
                    "score": row.get("fs"),
                    "reason": trig_yy if trig_yy else None,
                    "sub_items": []
                }

                sub_items = row.get("commonlxid", [])
                if sub_items:
                    for sub in sub_items:
                        sub_trig_yy = sub.get("trigyy") or ""
                        sub_trig_yy = sub_trig_yy.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
                        item["sub_items"].append({
                            "id": sub.get("id"),
                            "name": sub.get("lx", ""),
                            "trig": sub.get("trig", 0) == 1,
                            "level": sub.get("level"),
                            "score": sub.get("fs"),
                            "reason": sub_trig_yy if sub_trig_yy else None
                        })

                if item["trig"]:
                    risk_items.append(item)
                else:
                    safe_items.append(item)

            categories.append({
                "name": cat_name,
                "total": len(rows),
                "risk_count": len(risk_items),
                "risk_items": risk_items,
                "safe_items": safe_items
            })

        result = {
            "code": normalized_code,
            "name": name,
            "total": total,
            "risk_count": num,
            "safe_count": total - num,
            "score": score,
            "categories": categories,
            "source": "通达信"
        }

        return ok(result)

    except httpx.HTTPStatusError as e:
        logger.warning(f"获取风险分析数据HTTP错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到该股票的风险分析数据"
        )
    except Exception as e:
        logger.error(f"获取风险分析数据失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取风险分析数据失败: {str(e)}"
        )

