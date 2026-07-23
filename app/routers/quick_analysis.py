# -*- coding: utf-8 -*-
"""
速览分析 API 路由

⚠️ 【已废弃】此模块已废弃，请使用统一的分析入口 /api/analysis/single
支持 mode=quick 参数来执行速览分析，mode=deep 来执行深度分析

详细说明：
- 新入口: POST /api/analysis/single
- 请求参数中添加: parameters.mode = "quick" 或 "deep"
- 此模块仅用于向后兼容，新功能请勿使用
"""

import logging
import warnings
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal

from app.routers.auth_db import get_current_user
from app.services.quick_analysis_service import get_quick_analysis_service, QuickAnalysisResult

router = APIRouter()
logger = logging.getLogger("webapi")


class QuickAnalysisRequest(BaseModel):
    """速览分析请求"""
    stock_code: str = Field(..., description="股票代码", example="000001")
    stock_name: Optional[str] = Field(None, description="股票名称")


class QuickAnalysisResponse(BaseModel):
    """速览分析响应"""
    code: int = Field(0, description="状态码，0表示成功")
    message: str = Field("success", description="状态消息")
    data: Dict[str, Any] = Field(..., description="速览分析结果")


@router.post("/quick", response_model=Dict[str, Any])
async def quick_analysis(
    request: QuickAnalysisRequest,
    user: dict = Depends(get_current_user)
):
    """
    ⚠️ 【已废弃】执行速览分析

    请使用新的统一入口: POST /api/analysis/single
    请求参数中添加: parameters.mode = "quick"
    """
    warnings.warn(
        "⚠️ /api/quick 路由已废弃，请使用 POST /api/analysis/single "
        "并在 parameters 中添加 mode='quick'",
        DeprecationWarning,
        stacklevel=2
    )
    logger.warning("使用了已废弃的 /api/quick 路由，请迁移到 /api/analysis/single")

    try:
        logger.info(f"📊 收到速览分析请求: {request.stock_code}")

        # 执行速览分析
        service = get_quick_analysis_service()
        result = service.analyze(request.stock_code, request.stock_name)

        return {
            "code": 0,
            "message": "success",
            "data": result.to_dict(),
            "_deprecation_warning": "此接口已废弃，请使用 POST /api/analysis/single 并在 parameters 中添加 mode='quick'"
        }

    except Exception as e:
        logger.error(f"速览分析失败: {e}")
        return {
            "code": 1,
            "message": str(e),
            "data": None
        }


@router.get("/{stock_code}", response_model=Dict[str, Any])
async def get_quick_analysis(
    stock_code: str,
    user: dict = Depends(get_current_user)
):
    """
    ⚠️ 【已废弃】获取速览分析结果（GET 方式）

    请使用新的统一入口: POST /api/analysis/single
    请求参数中添加: parameters.mode = "quick"
    """
    warnings.warn(
        "⚠️ /api/quick/{stock_code} 路由已废弃，请使用 POST /api/analysis/single "
        "并在 parameters 中添加 mode='quick'",
        DeprecationWarning,
        stacklevel=2
    )
    logger.warning(f"使用了已废弃的 /api/quick/{stock_code} 路由")

    try:
        logger.info(f"📊 获取速览分析: {stock_code}")

        service = get_quick_analysis_service()
        result = service.analyze(stock_code)

        return {
            "code": 0,
            "message": "success",
            "data": result.to_dict(),
            "_deprecation_warning": "此接口已废弃，请使用 POST /api/analysis/single 并在 parameters 中添加 mode='quick'"
        }

    except Exception as e:
        logger.error(f"速览分析失败: {e}")
        return {
            "code": 1,
            "message": str(e),
            "data": None
        }


@router.post("/start", response_model=Dict[str, Any])
async def start_analysis(
    body: QuickAnalysisRequest,
    mode: Literal["quick", "deep"] = Query("quick", description="分析模式: quick=速览, deep=深度"),
    user: dict = Depends(get_current_user)
):
    """
    ⚠️ 【已废弃】开始分析任务（统一入口）

    请使用新的统一入口: POST /api/analysis/single
    请求参数中添加: parameters.mode = "quick" 或 "deep"

    此接口仅用于向后兼容，新功能请勿使用。
    """
    warnings.warn(
        "⚠️ /api/quick/start 路由已废弃，请使用 POST /api/analysis/single "
        "并在 parameters 中添加 mode='quick' 或 mode='deep'",
        DeprecationWarning,
        stacklevel=2
    )
    logger.warning(f"使用了已废弃的 /api/quick/start 路由，mode={mode}")

    try:
        stock_code = body.stock_code
        stock_name = body.stock_name
        logger.info(f"📊 开始分析: {stock_code}, mode={mode}")

        if mode == "quick":
            # 速览模式
            service = get_quick_analysis_service()
            result = service.analyze(stock_code, stock_name)

            return {
                "code": 0,
                "message": "success",
                "data": {
                    "mode": "quick",
                    "quick_result": result.to_dict()
                },
                "_deprecation_warning": "此接口已废弃，请使用 POST /api/analysis/single 并在 parameters 中添加 mode='quick'"
            }
        else:
            # 深度模式
            logger.warning("⚠️ 深度模式请使用 POST /api/analysis/single 并在 parameters 中添加 mode='deep'")
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "mode": "deep",
                    "status": "pending",
                    "_deprecation_warning": "此接口已废弃，请使用 POST /api/analysis/single 并在 parameters 中添加 mode='deep'"
                }
            }

    except Exception as e:
        logger.error(f"分析任务失败: {e}")
        return {
            "code": 1,
            "message": str(e),
            "data": None
        }
