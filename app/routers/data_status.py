"""
数据健康状态检查接口
提供系统数据新鲜度、数据源状态、最近同步时间等可观测性信息
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pymongo import ASCENDING

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data-status"])


async def _check_realtime_quotes_status() -> dict:
    """检查实时行情数据源状态"""
    try:
        from app.services.unified_quotes import get_unified_quotes
        # 使用纯6位代码（不带交易所后缀），以兼容腾讯/AKShare接口
        test_codes = ["000001", "600519"]
        result = get_unified_quotes(test_codes)

        if not result:
            return {
                "status": "unavailable",
                "message": "行情数据源不可用",
                "last_update": None,
            }

        # 计算最新的抓取时间
        latest_time = None
        for code, data in result.items():
            fetched_at = data.get("fetched_at")
            if fetched_at:
                if latest_time is None or fetched_at > latest_time:
                    latest_time = fetched_at

        return {
            "status": "healthy",
            "message": "行情数据源正常",
            "last_update": latest_time,
            "stocks_checked": len(result),
        }
    except Exception as e:
        logger.warning(f"实时行情状态检查失败: {e}")
        return {
            "status": "degraded",
            "message": f"行情数据源异常: {str(e)[:100]}",
            "last_update": None,
        }


async def _check_historical_data_status() -> dict:
    """检查历史K线数据状态"""
    try:
        db = get_mongo_db()
        # 查询最新的交易日数据
        latest_doc = await db["stock_daily_quotes"].find_one(
            {"period": "daily"},
            sort=[("trade_date", -1)],
        )

        if not latest_doc:
            return {
                "status": "unavailable",
                "latest_date": None,
                "message": "无历史K线数据",
                "coverage_count": 0,
            }

        latest_date = latest_doc.get("trade_date")
        # 估算覆盖的股票数量
        pipeline = [
            {"$match": {"period": "daily", "trade_date": latest_date}},
            {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
        ]
        coverage = await db["stock_daily_quotes"].aggregate(pipeline).to_list(1)
        coverage_count = coverage[0]["count"] if coverage else 0

        # 判断数据新鲜度
        now = datetime.now()
        if latest_date:
            try:
                latest_dt = None
                for fmt in ("%Y%m%d", "%Y-%m-%d"):
                    try:
                        latest_dt = datetime.strptime(str(latest_date), fmt)
                        break
                    except ValueError:
                        continue
                if latest_dt:
                    days_diff = (now - latest_dt).days
                    if days_diff <= 1:
                        status = "healthy"
                        message = f"数据最新 ({latest_date})"
                    elif days_diff <= 7:
                        status = "stale"
                        message = f"数据已过期 {days_diff} 天"
                    else:
                        status = "critical"
                        message = f"数据严重过期 {days_diff} 天"
                else:
                    status = "unknown"
                    message = "日期格式异常"
            except Exception:
                status = "unknown"
                message = "日期解析失败"
        else:
            status = "unknown"
            message = "无法判断新鲜度"

        return {
            "status": status,
            "latest_date": latest_date,
            "message": message,
            "coverage_count": coverage_count,
        }
    except Exception as e:
        logger.warning(f"历史数据状态检查失败: {e}")
        return {
            "status": "unknown",
            "latest_date": None,
            "message": f"检查失败: {str(e)[:100]}",
            "coverage_count": 0,
        }


async def _check_scheduler_status() -> dict:
    """检查定时任务执行状态"""
    try:
        db = get_mongo_db()

        # 查询最近的任务执行记录
        recent_executions = await db["scheduler_executions"].find(
            {},
            sort=[("started_at", -1)],
            limit=10,
        ).to_list(10)

        if not recent_executions:
            return {
                "status": "unknown",
                "message": "无任务执行记录",
                "recent_executions": [],
            }

        # 统计最近执行状态
        status_counts: dict[str, int] = {}
        for ex in recent_executions:
            status = ex.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "status": "healthy",
            "message": f"最近10次执行: {status_counts}",
            "recent_executions": [
                {
                    "job_id": ex.get("job_id"),
                    "status": ex.get("status"),
                    "started_at": ex.get("started_at").isoformat() if ex.get("started_at") else None,
                    "duration_seconds": ex.get("duration_seconds"),
                    "error": ex.get("error"),
                }
                for ex in recent_executions[:5]
            ],
        }
    except Exception as e:
        logger.warning(f"调度器状态检查失败: {e}")
        return {
            "status": "unknown",
            "message": f"检查失败: {str(e)[:100]}",
            "recent_executions": [],
        }


@router.get("/status")
async def get_data_status():
    """获取系统数据健康状态

    返回：
    - realtime_quotes: 实时行情数据源状态
    - historical_daily: 历史K线数据状态
    - scheduler: 定时任务执行状态
    - overall: 整体健康状态汇总
    """
    try:
        # 并行检查各项状态
        realtime_status = await _check_realtime_quotes_status()
        historical_status = await _check_historical_data_status()
        scheduler_status = await _check_scheduler_status()

        # 计算整体状态
        status_scores = {"healthy": 3, "stale": 2, "degraded": 2, "critical": 1, "unavailable": 0, "unknown": 1}
        scores = [
            status_scores.get(realtime_status["status"], 1),
            status_scores.get(historical_status["status"], 1),
            status_scores.get(scheduler_status["status"], 1),
        ]
        avg_score = sum(scores) / len(scores)

        if avg_score >= 2.5:
            overall_status = "healthy"
            overall_message = "系统数据状态良好"
        elif avg_score >= 1.5:
            overall_status = "degraded"
            overall_message = "部分数据源存在问题"
        else:
            overall_status = "critical"
            overall_message = "系统数据存在严重问题"

        return {
            "success": True,
            "data": {
                "overall": {
                    "status": overall_status,
                    "message": overall_message,
                    "checked_at": datetime.now().isoformat(),
                },
                "realtime_quotes": realtime_status,
                "historical_daily": historical_status,
                "scheduler": scheduler_status,
            },
        }
    except Exception as e:
        logger.error(f"获取数据状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取数据状态失败: {str(e)}")
