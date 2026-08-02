#!/usr/bin/env python
"""
定时任务管理路由
提供定时任务的查询、暂停、恢复、手动触发等功能
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.scheduler_service import SchedulerService, get_scheduler_service

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class JobTriggerRequest(BaseModel):
    """手动触发任务请求"""
    job_id: str
    kwargs: dict[str, Any] | None = None


class JobUpdateRequest(BaseModel):
    """更新任务请求"""
    job_id: str
    enabled: bool | None = None
    cron: str | None = None


class JobMetadataUpdateRequest(BaseModel):
    """更新任务元数据请求"""
    display_name: str | None = None
    description: str | None = None


@router.get("/jobs")
async def list_jobs(
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取所有定时任务列表
    
    Returns:
        任务列表，包含任务ID、名称、状态、下次执行时间等信息
    """
    try:
        jobs = await service.list_jobs()
        return ok(data=jobs, message=f"获取到 {len(jobs)} 个定时任务")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.put("/jobs/{job_id}/metadata")
async def update_job_metadata_route(
    job_id: str,
    request: JobMetadataUpdateRequest,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    更新任务元数据（触发器名称和备注）

    Args:
        job_id: 任务ID
        request: 更新请求

    Returns:
        操作结果
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以更新任务元数据")

    try:
        success = await service.update_job_metadata(
            job_id,
            display_name=request.display_name,
            description=request.description
        )
        if success:
            return ok(message=f"任务 {job_id} 元数据已更新")
        else:
            raise HTTPException(status_code=400, detail=f"更新任务 {job_id} 元数据失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新任务元数据失败: {str(e)}")


@router.get("/jobs/{job_id}")
async def get_job_detail(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取任务详情

    Args:
        job_id: 任务ID

    Returns:
        任务详细信息
    """
    try:
        job = await service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
        return ok(data=job, message="获取任务详情成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务详情失败: {str(e)}")


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    暂停任务
    
    Args:
        job_id: 任务ID
        
    Returns:
        操作结果
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以暂停任务")
    
    try:
        success = await service.pause_job(job_id)
        if success:
            return ok(message=f"任务 {job_id} 已暂停")
        else:
            raise HTTPException(status_code=400, detail=f"暂停任务 {job_id} 失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"暂停任务失败: {str(e)}")


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    恢复任务
    
    Args:
        job_id: 任务ID
        
    Returns:
        操作结果
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以恢复任务")
    
    try:
        success = await service.resume_job(job_id)
        if success:
            return ok(message=f"任务 {job_id} 已恢复")
        else:
            raise HTTPException(status_code=400, detail=f"恢复任务 {job_id} 失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复任务失败: {str(e)}")


@router.post("/jobs/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service),
    force: bool = Query(False, description="是否强制执行（跳过交易时间检查等）")
):
    """
    手动触发任务执行

    Args:
        job_id: 任务ID
        force: 是否强制执行（跳过交易时间检查等），默认 False

    Returns:
        操作结果
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以手动触发任务")

    try:
        # 为特定任务传递 force 参数
        kwargs = {}
        if force and job_id in ["tushare_quotes_sync", "akshare_quotes_sync"]:
            kwargs["force"] = True

        success = await service.trigger_job(job_id, kwargs=kwargs)
        if success:
            message = f"任务 {job_id} 已触发执行"
            if force:
                message += "（强制模式）"
            return ok(message=message)
        else:
            raise HTTPException(status_code=400, detail=f"触发任务 {job_id} 失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"触发任务失败: {str(e)}")


@router.get("/jobs/{job_id}/history")
async def get_job_history(
    job_id: str,
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取任务执行历史
    
    Args:
        job_id: 任务ID
        limit: 返回数量限制
        offset: 偏移量
        
    Returns:
        任务执行历史记录
    """
    try:
        history = await service.get_job_history(job_id, limit=limit, offset=offset)
        total = await service.count_job_history(job_id)
        
        return ok(
            data={
                "history": history,
                "total": total,
                "limit": limit,
                "offset": offset
            },
            message=f"获取到 {len(history)} 条执行记录"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行历史失败: {str(e)}")


@router.get("/history")
async def get_all_history(
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    job_id: str | None = Query(None, description="任务ID过滤"),
    status: str | None = Query(None, description="状态过滤: success/failed"),
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取所有任务执行历史
    
    Args:
        limit: 返回数量限制
        offset: 偏移量
        job_id: 任务ID过滤
        status: 状态过滤
        
    Returns:
        所有任务执行历史记录
    """
    try:
        history = await service.get_all_history(
            limit=limit,
            offset=offset,
            job_id=job_id,
            status=status
        )
        total = await service.count_all_history(job_id=job_id, status=status)
        
        return ok(
            data={
                "history": history,
                "total": total,
                "limit": limit,
                "offset": offset
            },
            message=f"获取到 {len(history)} 条执行记录"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行历史失败: {str(e)}")


@router.get("/stats")
async def get_scheduler_stats(
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取调度器统计信息
    
    Returns:
        调度器统计信息，包括任务总数、运行中任务数、暂停任务数等
    """
    try:
        stats = await service.get_stats()
        return ok(data=stats, message="获取统计信息成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/health")
async def scheduler_health_check(
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    调度器健康检查

    Returns:
        调度器健康状态
    """
    try:
        health = await service.health_check()
        return ok(data=health, message="调度器运行正常")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")


@router.get("/executions")
async def get_job_executions(
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service),
    job_id: str | None = Query(None, description="任务ID过滤"),
    status: str | None = Query(None, description="状态过滤（success/failed/missed/running）"),
    is_manual: bool | None = Query(None, description="是否手动触发（true=手动，false=自动，None=全部）"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    获取任务执行历史

    Args:
        job_id: 任务ID过滤（可选）
        status: 状态过滤（可选）
        is_manual: 是否手动触发（可选）
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        执行历史列表
    """
    try:
        executions = await service.get_job_executions(
            job_id=job_id,
            status=status,
            is_manual=is_manual,
            limit=limit,
            offset=offset
        )
        total = await service.count_job_executions(job_id=job_id, status=status, is_manual=is_manual)
        return ok(data={
            "items": executions,
            "total": total,
            "limit": limit,
            "offset": offset
        }, message=f"获取到 {len(executions)} 条执行记录")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行历史失败: {str(e)}")


@router.get("/jobs/{job_id}/executions")
async def get_single_job_executions(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service),
    status: str | None = Query(None, description="状态过滤（success/failed/missed/running）"),
    is_manual: bool | None = Query(None, description="是否手动触发（true=手动，false=自动，None=全部）"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    获取指定任务的执行历史

    Args:
        job_id: 任务ID
        status: 状态过滤（可选）
        is_manual: 是否手动触发（可选）
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        执行历史列表
    """
    try:
        executions = await service.get_job_executions(
            job_id=job_id,
            status=status,
            is_manual=is_manual,
            limit=limit,
            offset=offset
        )
        total = await service.count_job_executions(job_id=job_id, status=status, is_manual=is_manual)
        return ok(data={
            "items": executions,
            "total": total,
            "limit": limit,
            "offset": offset
        }, message=f"获取到 {len(executions)} 条执行记录")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取执行历史失败: {str(e)}")


@router.get("/jobs/{job_id}/execution-stats")
async def get_job_execution_stats(
    job_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    获取任务执行统计信息

    Args:
        job_id: 任务ID

    Returns:
        统计信息
    """
    try:
        stats = await service.get_job_execution_stats(job_id)
        return ok(data=stats, message="获取统计信息成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    取消/终止任务执行

    对于正在执行的任务，设置取消标记；
    对于已经退出但数据库中仍为running的任务，直接标记为failed

    Args:
        execution_id: 执行记录ID（MongoDB _id）

    Returns:
        操作结果
    """
    try:
        success = await service.cancel_job_execution(execution_id)
        if success:
            return ok(message="已设置取消标记，任务将在下次检查时停止")
        else:
            raise HTTPException(status_code=400, detail="取消任务失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@router.post("/executions/{execution_id}/mark-failed")
async def mark_execution_failed(
    execution_id: str,
    reason: str = Query("用户手动标记为失败", description="失败原因"),
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    将执行记录标记为失败状态

    用于处理已经退出但数据库中仍为running的任务

    Args:
        execution_id: 执行记录ID（MongoDB _id）
        reason: 失败原因

    Returns:
        操作结果
    """
    try:
        success = await service.mark_execution_as_failed(execution_id, reason)
        if success:
            return ok(message="已标记为失败状态")
        else:
            raise HTTPException(status_code=400, detail="标记失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"标记失败: {str(e)}")


@router.delete("/executions/{execution_id}")
async def delete_execution(
    execution_id: str,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    删除执行记录

    Args:
        execution_id: 执行记录ID（MongoDB _id）

    Returns:
        操作结果
    """
    try:
        success = await service.delete_execution(execution_id)
        if success:
            return ok(message="执行记录已删除")
        else:
            raise HTTPException(status_code=400, detail="删除失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除执行记录失败: {str(e)}")


# ==================== 批量定时任务操作 API ====================

class BatchUpdateRequest(BaseModel):
    """批量更新任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1, max_length=100)
    enabled: bool | None = Field(None, description="是否启用")
    cron_expression: str | None = Field(None, description="Cron 表达式")
    reset_failures: bool = Field(False, description="是否重置失败计数")


class BatchDeleteRequest(BaseModel):
    """批量删除任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1, max_length=100)


class BatchTriggerRequest(BaseModel):
    """批量触发任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1, max_length=100)
    force: bool = Field(False, description="是否强制执行")


class CreateFromFavoritesRequest(BaseModel):
    """从自选股创建定时任务请求"""
    task_type: str = Field("analysis", description="任务类型")
    cron_expression: str = Field(..., description="Cron 表达式")
    analysis_type: str | None = Field("comprehensive", description="分析类型")
    tags: list[str] | None = Field(None, description="自选股标签过滤")
    include_portfolio_context: bool = Field(True, description="是否包含持仓上下文")


@router.patch("/batch")
async def batch_update_jobs(
    request: BatchUpdateRequest,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    批量更新定时任务（启用/禁用/修改周期/重置失败计数）

    Args:
        job_ids: 任务ID列表（最多100个）
        enabled: 是否启用
        cron_expression: Cron 表达式
        reset_failures: 是否重置失败计数

    Returns:
        批量操作结果统计
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以批量更新任务")

    try:
        # 限制批量操作的任务数量
        if len(request.job_ids) > 100:
            raise HTTPException(status_code=400, detail="批量操作最多支持100个任务")

        results = await service.batch_update_jobs(
            job_ids=request.job_ids,
            enabled=request.enabled,
            cron_expression=request.cron_expression,
            reset_failures=request.reset_failures
        )
        return ok(data=results, message=f"批量更新完成: 成功 {results['success']}/{results['total']}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量更新任务失败: {str(e)}")


@router.post("/batch/delete")
async def batch_delete_jobs(
    request: BatchDeleteRequest,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    批量删除定时任务

    Args:
        job_ids: 任务ID列表（最多100个）

    Returns:
        批量操作结果统计
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以批量删除任务")

    try:
        # 限制批量操作的任务数量
        if len(request.job_ids) > 100:
            raise HTTPException(status_code=400, detail="批量操作最多支持100个任务")

        results = await service.batch_delete_jobs(job_ids=request.job_ids)
        return ok(data=results, message=f"批量删除完成: 成功 {results['success']}/{results['total']}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除任务失败: {str(e)}")


@router.post("/batch/trigger")
async def batch_trigger_jobs(
    request: BatchTriggerRequest,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    手动触发批量定时任务

    Args:
        job_ids: 任务ID列表（最多100个）
        force: 是否强制执行

    Returns:
        批量操作结果统计
    """
    # 检查管理员权限
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可以手动触发任务")

    try:
        # 限制批量操作的任务数量
        if len(request.job_ids) > 100:
            raise HTTPException(status_code=400, detail="批量操作最多支持100个任务")

        # 构建 kwargs
        kwargs = {"force": request.force} if request.force else None

        results = await service.batch_trigger_jobs(
            job_ids=request.job_ids,
            kwargs=kwargs
        )
        return ok(data=results, message=f"批量触发完成: 成功 {results['success']}/{results['total']}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量触发任务失败: {str(e)}")


@router.post("/from-favorites")
async def create_jobs_from_favorites(
    request: CreateFromFavoritesRequest,
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    从自选股批量创建定时任务

    根据用户自选股创建对应的定时分析任务，支持按标签过滤

    Args:
        task_type: 任务类型（默认 analysis）
        cron_expression: Cron 表达式（如 "0 9 * * 1-5" 表示工作日9点）
        analysis_type: 分析类型（默认 comprehensive）
        tags: 自选股标签过滤（可选）
        include_portfolio_context: 是否包含持仓上下文

    Returns:
        创建结果统计
    """
    try:
        logger.info(f"📋 从自选股创建定时任务: user_id={user['id']}, cron={request.cron_expression}, tags={request.tags}")

        results = await service.create_jobs_from_favorites(
            user_id=user["id"],
            task_type=request.task_type,
            cron_expression=request.cron_expression,
            analysis_type=request.analysis_type,
            tags=request.tags,
            include_portfolio_context=request.include_portfolio_context
        )

        message = f"从自选股创建任务完成: 成功 {results['success']}/{results['total']}"
        if results.get("errors"):
            message += f"，失败原因: {results['errors'][:3]}"  # 只显示前3个错误

        return ok(data=results, message=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 从自选股创建定时任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"从自选股创建定时任务失败: {str(e)}")


@router.get("/jobs-with-metadata")
async def list_jobs_with_metadata(
    user: dict = Depends(get_current_user),
    service: SchedulerService = Depends(get_scheduler_service),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    获取所有定时任务列表（包含详细元数据）

    返回任务列表及其关联的元数据，包括失败计数、持仓上下文等

    Args:
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        任务列表，包含任务ID、名称、状态、下次执行时间及详细元数据
    """
    try:
        jobs = await service.list_jobs()

        # 为每个任务获取元数据
        enriched_jobs = []
        for job in jobs:
            job_id = job.get("id")
            if job_id:
                metadata = await service._get_job_metadata(job_id)
                if metadata:
                    job["metadata"] = {
                        "display_name": metadata.get("display_name"),
                        "description": metadata.get("description"),
                        "consecutive_failures": metadata.get("consecutive_failures", 0),
                        "max_consecutive_failures": metadata.get("max_consecutive_failures", 3),
                        "last_success_at": metadata.get("last_success_at"),
                        "last_failure_at": metadata.get("last_failure_at"),
                        "enabled": metadata.get("enabled", True),
                        "portfolio_context": metadata.get("portfolio_context"),
                        "task_type": metadata.get("task_type"),
                        "symbols": metadata.get("symbols", [])
                    }
                else:
                    job["metadata"] = None
            enriched_jobs.append(job)

        # 分页
        paginated_jobs = enriched_jobs[offset:offset + limit]

        return ok(
            data={
                "items": paginated_jobs,
                "total": len(enriched_jobs),
                "limit": limit,
                "offset": offset
            },
            message=f"获取到 {len(paginated_jobs)} 个定时任务"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


# ==================== 数据完整性检查 ====================

@router.post("/data-integrity/check")
async def trigger_data_integrity_check(
    trade_date: str | None = Query(None, description="指定交易日期 (YYYY-MM-DD)，留空自动检测"),
    auto_remediate: bool = Query(True, description="是否自动补数"),
    remediate_source: str = Query("akshare", description="补数数据源"),
    user: dict = Depends(get_current_user),
):
    """
    手动触发数据完整性检查

    - 检查 stock_daily_quotes 中最新交易日的数据完整性
    - 识别缺失股票并用备用数据源自动补数
    - 返回检查结果
    """
    try:
        from app.services.data_integrity_service import get_data_integrity_service
        service = await get_data_integrity_service()
        result = await service.check_historical_completeness(
            trade_date=trade_date,
            auto_remediate=auto_remediate,
            remediate_source=remediate_source,
        )
        return ok(
            data=result,
            message=f"完整性检查完成: {result.get('status')} "
                   f"(期望 {result.get('expected_count')}, 实际 {result.get('actual_count')}, "
                   f"缺失 {result.get('missing_count')}, 补数 {result.get('remediated_count')})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"完整性检查失败: {str(e)}")


@router.get("/data-integrity/latest")
async def get_latest_integrity_check(
    user: dict = Depends(get_current_user),
):
    """获取最近一次数据完整性检查结果"""
    try:
        from app.services.data_integrity_service import get_data_integrity_service
        service = await get_data_integrity_service()
        result = await service.get_latest_check_result()
        if result:
            return ok(data=result, message="获取完整性检查结果成功")
        else:
            return ok(data=None, message="尚未执行过完整性检查")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取检查结果失败: {str(e)}")
