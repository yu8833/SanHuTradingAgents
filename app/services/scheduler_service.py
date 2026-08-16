#!/usr/bin/env python
"""
定时任务管理服务
提供定时任务的查询、暂停、恢复、手动触发等功能
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import get_mongo_db

try:
    from tradingagents.utils.logging_manager import get_logger
except ImportError:
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)
from app.utils.timezone import now_tz

logger = get_logger(__name__)

# UTC+8 时区
UTC_8 = timezone(timedelta(hours=8))


def get_utc8_now():
    """
    获取 UTC+8 当前时间（naive datetime）

    注意：返回 naive datetime（不带时区信息），MongoDB 会按原样存储本地时间值
    这样前端可以直接添加 +08:00 后缀显示
    """
    return now_tz().replace(tzinfo=None)


# 长时间运行任务的僵尸检测阈值（小时）
# 历史同步等任务运行时间较长，使用更宽松的阈值
LONG_RUNNING_THRESHOLD_HOURS = 6


# 一次性补跑任务（catch-up）识别规则：id 以 `_catchup` 结尾，或名称以 `启动补跑-` 开头。
# 这类任务只在服务启动时临时注册、执行一次即完成，不应出现在 /tasks 任务列表中，
# 否则会造成"任务太多、无法分辨"的错觉。
CATCHUP_ID_SUFFIX = "_catchup"
CATCHUP_NAME_PREFIX = "启动补跑-"

# 系统内部维护任务（非用户数据任务，不应展示在任务列表，用户无需管理）
INTERNAL_JOB_IDS = {"check_zombie_tasks"}


def _is_transient_catchup_job(job_id: str, job_name: str) -> bool:
    """判断是否为一次性的启动补跑任务（应从任务列表隐藏）。"""
    return job_id.endswith(CATCHUP_ID_SUFFIX) or (job_name or "").startswith(CATCHUP_NAME_PREFIX)


def _is_internal_job(job_id: str) -> bool:
    """判断是否为系统内部维护任务（如僵尸检测），应从任务列表隐藏。"""
    return job_id in INTERNAL_JOB_IDS


# 模块级同步 MongoDB 客户端单例（供 update_job_progress 等同步函数使用）
# 避免每次调用都新建 MongoClient，减少连接开销和事件循环阻塞
_sync_mongo_client = None


def _get_sync_db():
    """获取同步 MongoDB 数据库单例"""
    global _sync_mongo_client
    if _sync_mongo_client is None:
        from pymongo import MongoClient

        from app.core.config import settings
        _sync_mongo_client = MongoClient(settings.MONGO_URI)
    return _sync_mongo_client[settings.MONGO_DB]


class TaskCancelledException(Exception):
    """任务被取消异常"""
    pass


class SchedulerService:
    """定时任务管理服务"""

    def __init__(self, scheduler: AsyncIOScheduler):
        """
        初始化服务

        Args:
            scheduler: APScheduler调度器实例
        """
        self.scheduler = scheduler
        self.db = None

        # 记录手动触发时临时恢复的任务，回调中用于恢复原状态
        # {job_id: {"was_paused": bool}}
        self._temporary_resumes = {}

        # 记录任务实际开始执行的时间（SUBMITTED 事件），用于精确计算 execution_time
        # {job_id: datetime}
        self._job_start_times = {}

        # 添加事件监听器，监控任务执行
        self._setup_event_listeners()
    
    def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db
    
    async def list_jobs(self) -> list[dict[str, Any]]:
        """
        获取所有定时任务列表

        Returns:
            任务列表
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            # 隐藏一次性启动补跑任务与系统内部维护任务，避免任务列表"又乱又多"
            if _is_transient_catchup_job(job.id, job.name) or _is_internal_job(job.id):
                continue
            job_dict = self._job_to_dict(job)
            # 获取任务元数据（触发器名称和备注）
            metadata = await self._get_job_metadata(job.id)
            if metadata:
                job_dict["display_name"] = metadata.get("display_name")
                job_dict["description"] = metadata.get("description")
            jobs.append(job_dict)

        logger.info(f"📋 获取到 {len(jobs)} 个定时任务")
        return jobs
    
    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        获取任务详情

        Args:
            job_id: 任务ID

        Returns:
            任务详情，如果不存在则返回None
        """
        job = self.scheduler.get_job(job_id)
        if job:
            job_dict = self._job_to_dict(job, include_details=True)
            # 获取任务元数据
            metadata = await self._get_job_metadata(job_id)
            if metadata:
                job_dict["display_name"] = metadata.get("display_name")
                job_dict["description"] = metadata.get("description")
            return job_dict
        return None
    
    async def pause_job(self, job_id: str) -> bool:
        """
        暂停任务
        
        Args:
            job_id: 任务ID
            
        Returns:
            是否成功
        """
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"⏸️ 任务 {job_id} 已暂停")
            
            # 记录操作历史
            await self._record_job_action(job_id, "pause", "success")
            return True
        except Exception as e:
            logger.error(f"❌ 暂停任务 {job_id} 失败: {e}")
            await self._record_job_action(job_id, "pause", "failed", str(e))
            return False
    
    async def resume_job(self, job_id: str) -> bool:
        """
        恢复任务
        
        Args:
            job_id: 任务ID
            
        Returns:
            是否成功
        """
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"▶️ 任务 {job_id} 已恢复")
            
            # 记录操作历史
            await self._record_job_action(job_id, "resume", "success")
            return True
        except Exception as e:
            logger.error(f"❌ 恢复任务 {job_id} 失败: {e}")
            await self._record_job_action(job_id, "resume", "failed", str(e))
            return False
    
    async def trigger_job(self, job_id: str, kwargs: dict[str, Any] | None = None) -> bool:
        """
        手动触发任务执行

        注意：如果任务处于暂停状态，会临时恢复任务以执行一次，执行完成后会重新暂停。
        不修改任务的 kwargs 配置，避免参数被永久固化。

        Args:
            job_id: 任务ID
            kwargs: 传递给任务函数的关键字参数（可选，仅记录到执行历史，不修改原任务配置）

        Returns:
            是否成功
        """
        try:
            job = self.scheduler.get_job(job_id)
            if not job:
                logger.error(f"❌ 任务 {job_id} 不存在")
                return False

            # 检查任务是否被暂停（next_run_time 为 None 表示暂停）
            was_paused = job.next_run_time is None
            if was_paused:
                logger.warning(f"⚠️ 任务 {job_id} 处于暂停状态，临时恢复以执行一次")
                self.scheduler.resume_job(job_id)
                # 重新获取 job 对象（恢复后状态已改变）
                job = self.scheduler.get_job(job_id)
                logger.info(f"✅ 任务 {job_id} 已临时恢复")

            # 记录临时恢复信息，回调中用于重新暂停任务
            # 注意：不修改 job.kwargs，避免参数被永久固化
            self._temporary_resumes[job_id] = {"was_paused": was_paused}

            if kwargs:
                logger.info(f"📝 任务 {job_id} 收到手动触发参数（仅记录，不修改原任务配置）: {kwargs}")

            # 手动触发任务 - 使用北京时间
            now = now_tz()
            job.modify(next_run_time=now)
            logger.info(f"🚀 手动触发任务 {job_id} (next_run_time={now}, was_paused={was_paused}, kwargs={kwargs})")

            # 记录操作历史
            action_note = f"手动触发执行 (暂停状态: {was_paused}"
            if kwargs:
                action_note += f", 参数: {kwargs}"
            action_note += ")"
            await self._record_job_action(job_id, "trigger", "success", action_note)

            # 立即创建一个"running"状态的执行记录，让用户能看到任务正在执行
            # 🔥 使用本地时间（naive datetime）
            await self._record_job_execution(
                job_id=job_id,
                status="running",
                scheduled_time=get_utc8_now(),  # 使用本地时间（naive datetime）
                progress=0,
                is_manual=True  # 标记为手动触发
            )

            return True
        except Exception as e:
            logger.error(f"❌ 触发任务 {job_id} 失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            await self._record_job_action(job_id, "trigger", "failed", str(e))
            return False
    
    async def get_job_history(
        self,
        job_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        """
        获取任务执行历史
        
        Args:
            job_id: 任务ID
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            执行历史记录
        """
        try:
            db = self._get_db()
            cursor = db.scheduler_history.find(
                {"job_id": job_id}
            ).sort("timestamp", -1).skip(offset).limit(limit)
            
            history = []
            async for doc in cursor:
                doc.pop("_id", None)
                history.append(doc)
            
            return history
        except Exception as e:
            logger.error(f"❌ 获取任务 {job_id} 执行历史失败: {e}")
            return []
    
    async def count_job_history(self, job_id: str) -> int:
        """
        统计任务执行历史数量
        
        Args:
            job_id: 任务ID
            
        Returns:
            历史记录数量
        """
        try:
            db = self._get_db()
            count = await db.scheduler_history.count_documents({"job_id": job_id})
            return count
        except Exception as e:
            logger.error(f"❌ 统计任务 {job_id} 执行历史失败: {e}")
            return 0
    
    async def get_all_history(
        self,
        limit: int = 50,
        offset: int = 0,
        job_id: str | None = None,
        status: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取所有任务执行历史
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
            job_id: 任务ID过滤
            status: 状态过滤
            
        Returns:
            执行历史记录
        """
        try:
            db = self._get_db()
            
            # 构建查询条件
            query = {}
            if job_id:
                query["job_id"] = job_id
            if status:
                query["status"] = status
            
            cursor = db.scheduler_history.find(query).sort("timestamp", -1).skip(offset).limit(limit)
            
            history = []
            async for doc in cursor:
                doc.pop("_id", None)
                history.append(doc)
            
            return history
        except Exception as e:
            logger.error(f"❌ 获取执行历史失败: {e}")
            return []
    
    async def count_all_history(
        self,
        job_id: str | None = None,
        status: str | None = None
    ) -> int:
        """
        统计所有任务执行历史数量

        Args:
            job_id: 任务ID过滤
            status: 状态过滤

        Returns:
            历史记录数量
        """
        try:
            db = self._get_db()

            # 构建查询条件
            query = {}
            if job_id:
                query["job_id"] = job_id
            if status:
                query["status"] = status

            count = await db.scheduler_history.count_documents(query)
            return count
        except Exception as e:
            logger.error(f"❌ 统计执行历史失败: {e}")
            return 0

    async def get_job_executions(
        self,
        job_id: str | None = None,
        status: str | None = None,
        is_manual: bool | None = None,
        limit: int = 50,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        """
        获取任务执行历史

        Args:
            job_id: 任务ID（可选，不指定则返回所有任务）
            status: 状态过滤（success/failed/missed/running）
            is_manual: 是否手动触发（True=手动，False=自动，None=全部）
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            执行历史列表
        """
        try:
            db = self._get_db()

            # 构建查询条件
            query = {}
            if job_id:
                query["job_id"] = job_id
            if status:
                query["status"] = status

            # 处理 is_manual 过滤
            if is_manual is not None:
                if is_manual:
                    # 手动触发：is_manual 必须为 true
                    query["is_manual"] = True
                else:
                    # 自动触发：is_manual 字段不存在或为 false
                    # 使用 $ne (not equal) 来排除 is_manual=true 的记录
                    query["is_manual"] = {"$ne": True}

            cursor = db.scheduler_executions.find(query).sort("timestamp", -1).skip(offset).limit(limit)

            executions = []
            async for doc in cursor:
                # 转换 _id 为字符串
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])

                # 格式化时间（MongoDB 存储的是 naive datetime，表示本地时间）
                # 直接序列化为 ISO 格式字符串，前端会自动添加 +08:00 后缀
                for time_field in ["scheduled_time", "timestamp", "updated_at"]:
                    if doc.get(time_field):
                        dt = doc[time_field]
                        # 如果是 datetime 对象，转换为 ISO 格式字符串
                        if hasattr(dt, 'isoformat'):
                            doc[time_field] = dt.isoformat()

                executions.append(doc)

            return executions
        except Exception as e:
            logger.error(f"❌ 获取任务执行历史失败: {e}")
            return []

    async def count_job_executions(
        self,
        job_id: str | None = None,
        status: str | None = None,
        is_manual: bool | None = None
    ) -> int:
        """
        统计任务执行历史数量

        Args:
            job_id: 任务ID（可选）
            status: 状态过滤（可选）
            is_manual: 是否手动触发（可选）

        Returns:
            执行历史数量
        """
        try:
            db = self._get_db()

            # 构建查询条件
            query = {}
            if job_id:
                query["job_id"] = job_id
            if status:
                query["status"] = status

            # 处理 is_manual 过滤
            if is_manual is not None:
                if is_manual:
                    # 手动触发：is_manual 必须为 true
                    query["is_manual"] = True
                else:
                    # 自动触发：is_manual 字段不存在或为 false
                    query["is_manual"] = {"$ne": True}

            count = await db.scheduler_executions.count_documents(query)
            return count
        except Exception as e:
            logger.error(f"❌ 统计任务执行历史失败: {e}")
            return 0

    async def cancel_job_execution(self, execution_id: str) -> bool:
        """
        取消/终止任务执行

        对于正在执行的任务，设置取消标记；
        对于已经退出但数据库中仍为running的任务，直接标记为failed

        Args:
            execution_id: 执行记录ID（MongoDB _id）

        Returns:
            是否成功
        """
        try:
            from bson import ObjectId
            db = self._get_db()

            # 查找执行记录
            execution = await db.scheduler_executions.find_one({"_id": ObjectId(execution_id)})
            if not execution:
                logger.error(f"❌ 执行记录不存在: {execution_id}")
                return False

            if execution.get("status") != "running":
                logger.warning(f"⚠️ 执行记录状态不是running: {execution_id} (status={execution.get('status')})")
                return False

            # 设置取消标记
            await db.scheduler_executions.update_one(
                {"_id": ObjectId(execution_id)},
                {
                    "$set": {
                        "cancel_requested": True,
                        "updated_at": get_utc8_now()
                    }
                }
            )

            logger.info(f"✅ 已设置取消标记: {execution.get('job_name', execution.get('job_id'))} (execution_id={execution_id})")
            return True

        except Exception as e:
            logger.error(f"❌ 取消任务执行失败: {e}")
            return False

    async def mark_execution_as_failed(self, execution_id: str, reason: str = "用户手动标记为失败") -> bool:
        """
        将执行记录标记为失败状态

        用于处理已经退出但数据库中仍为running的任务

        Args:
            execution_id: 执行记录ID（MongoDB _id）
            reason: 失败原因

        Returns:
            是否成功
        """
        try:
            from bson import ObjectId
            db = self._get_db()

            # 查找执行记录
            execution = await db.scheduler_executions.find_one({"_id": ObjectId(execution_id)})
            if not execution:
                logger.error(f"❌ 执行记录不存在: {execution_id}")
                return False

            # 更新为failed状态
            await db.scheduler_executions.update_one(
                {"_id": ObjectId(execution_id)},
                {
                    "$set": {
                        "status": "failed",
                        "error_message": reason,
                        "updated_at": get_utc8_now()
                    }
                }
            )

            logger.info(f"✅ 已标记为失败: {execution.get('job_name', execution.get('job_id'))} (execution_id={execution_id}, reason={reason})")
            return True

        except Exception as e:
            logger.error(f"❌ 标记执行记录为失败失败: {e}")
            return False

    async def delete_execution(self, execution_id: str) -> bool:
        """
        删除执行记录

        Args:
            execution_id: 执行记录ID（MongoDB _id）

        Returns:
            是否成功
        """
        try:
            from bson import ObjectId
            db = self._get_db()

            # 查找执行记录
            execution = await db.scheduler_executions.find_one({"_id": ObjectId(execution_id)})
            if not execution:
                logger.error(f"❌ 执行记录不存在: {execution_id}")
                return False

            # 不允许删除正在执行的任务
            if execution.get("status") == "running":
                logger.error(f"❌ 不能删除正在执行的任务: {execution_id}")
                return False

            # 删除记录
            result = await db.scheduler_executions.delete_one({"_id": ObjectId(execution_id)})

            if result.deleted_count > 0:
                logger.info(f"✅ 已删除执行记录: {execution.get('job_name', execution.get('job_id'))} (execution_id={execution_id})")
                return True
            else:
                logger.error(f"❌ 删除执行记录失败: {execution_id}")
                return False

        except Exception as e:
            logger.error(f"❌ 删除执行记录失败: {e}")
            return False

    async def get_job_execution_stats(self, job_id: str) -> dict[str, Any]:
        """
        获取任务执行统计信息

        Args:
            job_id: 任务ID

        Returns:
            统计信息
        """
        try:
            db = self._get_db()

            # 统计各状态的执行次数
            pipeline = [
                {"$match": {"job_id": job_id}},
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "avg_execution_time": {"$avg": "$execution_time"}
                }}
            ]

            stats = {
                "total": 0,
                "success": 0,
                "failed": 0,
                "missed": 0,
                "avg_execution_time": 0
            }

            async for doc in db.scheduler_executions.aggregate(pipeline):
                status = doc["_id"]
                count = doc["count"]
                stats["total"] += count
                stats[status] = count

                if status == "success" and doc.get("avg_execution_time"):
                    stats["avg_execution_time"] = round(doc["avg_execution_time"], 2)

            # 获取最近一次执行
            last_execution = await db.scheduler_executions.find_one(
                {"job_id": job_id},
                sort=[("timestamp", -1)]
            )

            if last_execution:
                stats["last_execution"] = {
                    "status": last_execution.get("status"),
                    "timestamp": last_execution.get("timestamp").isoformat() if last_execution.get("timestamp") else None,
                    "execution_time": last_execution.get("execution_time")
                }

            return stats
        except Exception as e:
            logger.error(f"❌ 获取任务执行统计失败: {e}")
            return {}
    
    async def get_stats(self) -> dict[str, Any]:
        """
        获取调度器统计信息
        
        Returns:
            统计信息
        """
        jobs = self.scheduler.get_jobs()
        
        total = len(jobs)
        running = sum(1 for job in jobs if job.next_run_time is not None)
        paused = total - running
        
        return {
            "total_jobs": total,
            "running_jobs": running,
            "paused_jobs": paused,
            "scheduler_running": self.scheduler.running,
            "scheduler_state": self.scheduler.state
        }
    
    async def health_check(self) -> dict[str, Any]:
        """
        调度器健康检查
        
        Returns:
            健康状态
        """
        return {
            "status": "healthy" if self.scheduler.running else "stopped",
            "running": self.scheduler.running,
            "state": self.scheduler.state,
            "timestamp": get_utc8_now().isoformat()
        }
    
    def _job_to_dict(self, job: Job, include_details: bool = False) -> dict[str, Any]:
        """
        将Job对象转换为字典
        
        Args:
            job: Job对象
            include_details: 是否包含详细信息
            
        Returns:
            字典表示
        """
        result = {
            "id": job.id,
            "name": job.name or job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "paused": job.next_run_time is None,
            "trigger": str(job.trigger),
        }
        
        if include_details:
            result.update({
                "func": f"{job.func.__module__}.{job.func.__name__}",
                "args": job.args,
                "kwargs": job.kwargs,
                "misfire_grace_time": job.misfire_grace_time,
                "max_instances": job.max_instances,
            })
        
        return result
    
    def _setup_event_listeners(self):
        """设置APScheduler事件监听器"""
        # 监听任务执行成功事件
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )

        # 监听任务执行失败事件
        self.scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )

        # 监听任务错过执行事件
        self.scheduler.add_listener(
            self._on_job_missed,
            EVENT_JOB_MISSED
        )

        # 监听任务开始执行事件（任务被提交到执行器时触发）
        # 用于创建 running 记录和记录实际开始时间
        self.scheduler.add_listener(
            self._on_job_submitted,
            EVENT_JOB_SUBMITTED
        )

        logger.info("✅ APScheduler事件监听器已设置")

        # 添加定时任务，检测僵尸任务（长时间处于running状态）
        self.scheduler.add_job(
            self._check_zombie_tasks,
            'interval',
            minutes=5,
            id='check_zombie_tasks',
            name='检测僵尸任务',
            replace_existing=True
        )
        logger.info("✅ 僵尸任务检测定时任务已添加")

    # 历史数据同步类任务需要长时间运行，排除在僵尸检测之外
    LONG_RUNNING_JOBS = {
        "tushare_historical_sync",
        "akshare_historical_sync",
        "baostock_historical_sync",
        "tushare_financial_sync",
        "akshare_financial_sync",
        "data_integrity_check",
    }

    async def _check_zombie_tasks(self):
        """检测僵尸任务（长时间处于running状态的任务）

        普通任务超过 30 分钟视为僵尸；LONG_RUNNING_JOBS 中的长任务超过 6 小时才视为僵尸。
        这样长任务在进程崩溃后也能被清理，同时避免误杀正常的长任务。
        """
        try:
            db = self._get_db()

            now = get_utc8_now()
            # 普通任务：30 分钟阈值
            normal_threshold = now - timedelta(minutes=30)
            # 长时间运行任务：6 小时阈值
            long_threshold = now - timedelta(hours=LONG_RUNNING_THRESHOLD_HOURS)

            long_job_ids = list(self.LONG_RUNNING_JOBS)

            # 查询：普通任务超 30 分钟 OR 长任务超 6 小时
            zombie_tasks = await db.scheduler_executions.find({
                "status": "running",
                "$or": [
                    {
                        "job_id": {"$nin": long_job_ids},
                        "timestamp": {"$lt": normal_threshold}
                    },
                    {
                        "job_id": {"$in": long_job_ids},
                        "timestamp": {"$lt": long_threshold}
                    }
                ]
            }).to_list(length=100)

            for task in zombie_tasks:
                # 更新为failed状态
                await db.scheduler_executions.update_one(
                    {"_id": task["_id"]},
                    {
                        "$set": {
                            "status": "failed",
                            "error_message": "任务执行超时或进程异常终止",
                            "updated_at": get_utc8_now()
                        }
                    }
                )
                logger.warning(f"⚠️ 检测到僵尸任务: {task.get('job_name', task.get('job_id'))} (开始时间: {task.get('timestamp')})")

            if zombie_tasks:
                logger.info(f"✅ 已标记 {len(zombie_tasks)} 个僵尸任务为失败状态")

            # 顺带清理僵尸回测任务：回测在 web 进程守护线程执行，若后端被重启/崩溃，
            # 线程被杀后 Redis 中会残留长时间无更新的 running 任务，前端据此外推出离谱 ETA。
            # 复用本周期任务（每 5 分钟）弥补启动清理的空窗。
            try:
                from app.strategy_system.task_manager import cleanup_stale_tasks
                _cleaned = cleanup_stale_tasks()
                if _cleaned:
                    logger.warning(f"🧹 已清理 {_cleaned} 个僵尸回测任务（标记为失败）")
            except Exception as _e:
                logger.warning(f"⚠️ 僵尸回测任务清理失败: {_e}")

        except Exception as e:
            logger.error(f"❌ 检测僵尸任务失败: {e}")

    def _on_job_submitted(self, event: JobSubmissionEvent):
        """任务开始执行回调（任务被提交到执行器时触发）

        - 记录实际开始执行时间，用于精确计算 execution_time
        - 为自动触发的任务创建 running 记录（手动触发的已在 trigger_job 中创建）
        """
        # 记录实际开始执行时间（用于计算 execution_time）
        self._job_start_times[event.job_id] = now_tz()

        # 修复：JobSubmissionEvent 的属性是 scheduled_run_times（复数，列表），
        # 不是 scheduled_run_time（单数）。JobExecutionEvent 才有 scheduled_run_time。
        scheduled_times = getattr(event, 'scheduled_run_times', None) or []
        scheduled_time = scheduled_times[0] if scheduled_times else None

        # 创建 running 记录（_record_job_execution 内部会做去重，避免与手动触发重复）
        asyncio.create_task(self._record_job_execution(
            job_id=event.job_id,
            status="running",
            scheduled_time=scheduled_time,
            progress=0,
            is_manual=False  # 自动触发
        ))

    def _on_job_executed(self, event: JobExecutionEvent):
        """任务执行成功回调"""
        # 计算实际执行时间（基于 SUBMITTED 事件记录的开始时间）
        start_time = self._job_start_times.pop(event.job_id, None)
        if start_time is not None:
            execution_time = (now_tz() - start_time).total_seconds()
        else:
            # 兜底：使用 scheduled_run_time 估算（包含调度延迟，不精确）
            execution_time = None
            if event.scheduled_run_time:
                now = datetime.now(event.scheduled_run_time.tzinfo)
                execution_time = (now - event.scheduled_run_time).total_seconds()

        asyncio.create_task(self._record_job_execution(
            job_id=event.job_id,
            status="success",
            scheduled_time=event.scheduled_run_time,
            execution_time=execution_time,
            return_value=str(event.retval) if event.retval else None,
            progress=100  # 任务完成，进度100%
        ))

        # 处理手动触发的临时恢复：执行完毕后重新暂停
        self._handle_temporary_resume(event.job_id)

    def _on_job_error(self, event: JobExecutionEvent):
        """任务执行失败回调"""
        # 计算实际执行时间（基于 SUBMITTED 事件记录的开始时间）
        start_time = self._job_start_times.pop(event.job_id, None)
        if start_time is not None:
            execution_time = (now_tz() - start_time).total_seconds()
        else:
            # 兜底：使用 scheduled_run_time 估算（包含调度延迟，不精确）
            execution_time = None
            if event.scheduled_run_time:
                now = datetime.now(event.scheduled_run_time.tzinfo)
                execution_time = (now - event.scheduled_run_time).total_seconds()

        asyncio.create_task(self._record_job_execution(
            job_id=event.job_id,
            status="failed",
            scheduled_time=event.scheduled_run_time,
            execution_time=execution_time,
            error_message=str(event.exception) if event.exception else None,
            traceback=event.traceback if hasattr(event, 'traceback') else None,
            progress=None  # 失败时不设置进度
        ))

        # 处理手动触发的临时恢复：执行完毕后重新暂停
        self._handle_temporary_resume(event.job_id)

    def _handle_temporary_resume(self, job_id: str):
        """处理手动触发的临时恢复：如果任务原本是暂停状态，执行完毕后重新暂停。

        Args:
            job_id: 任务ID
        """
        temp_info = self._temporary_resumes.pop(job_id, None)
        if temp_info and temp_info.get("was_paused"):
            try:
                self.scheduler.pause_job(job_id)
                logger.info(f"⏸️ 任务 {job_id} 手动触发执行完毕，已重新暂停（恢复原状态）")
            except Exception as e:
                logger.error(f"❌ 重新暂停任务 {job_id} 失败: {e}")

    def _on_job_missed(self, event: JobExecutionEvent):
        """任务错过执行回调"""
        # 错过执行的任务不会有 SUBMITTED/EXECUTED/ERROR 事件，清理可能残留的开始时间
        self._job_start_times.pop(event.job_id, None)
        # 错过执行也应清理临时恢复标记（任务实际未执行）
        self._temporary_resumes.pop(event.job_id, None)

        asyncio.create_task(self._record_job_execution(
            job_id=event.job_id,
            status="missed",
            scheduled_time=event.scheduled_run_time,
            progress=None  # 错过时不设置进度
        ))

    async def _record_job_execution(
        self,
        job_id: str,
        status: str,
        scheduled_time: datetime = None,
        execution_time: float = None,
        return_value: str = None,
        error_message: str = None,
        traceback: str = None,
        progress: int = None,
        is_manual: bool = False
    ):
        """
        记录任务执行历史

        Args:
            job_id: 任务ID
            status: 状态 (running/success/failed/missed)
            scheduled_time: 计划执行时间
            execution_time: 实际执行时长（秒）
            return_value: 返回值
            error_message: 错误信息
            traceback: 错误堆栈
            progress: 执行进度（0-100）
            is_manual: 是否手动触发
        """
        try:
            db = self._get_db()

            # 获取任务名称
            job = self.scheduler.get_job(job_id)
            job_name = job.name if job else job_id

            # 统一把 scheduled_time 转为 naive 本地时间（北京时间），
            # 作为"同一次调度"的关联键，供 running / 终态记录互相匹配。
            scheduled_naive = None
            if scheduled_time:
                if scheduled_time.tzinfo is not None:
                    scheduled_naive = scheduled_time.astimezone(UTC_8).replace(tzinfo=None)
                else:
                    scheduled_naive = scheduled_time

            # 如果是 running 状态，检查是否已有近期的 running 记录（1 分钟内）
            # 避免手动触发的 trigger_job 和 SUBMITTED 事件重复创建 running 记录
            if status == "running":
                recent_window = get_utc8_now() - timedelta(minutes=1)
                existing_running = await db.scheduler_executions.find_one({
                    "job_id": job_id,
                    "status": "running",
                    "timestamp": {"$gte": recent_window}
                })
                if existing_running:
                    logger.debug(f"ℹ️ 任务 {job_id} 已有近期的 running 记录，跳过重复创建")
                    return

                # 🔥 修复孤儿 running 记录：SUBMITTED 与 EXECUTED 事件分别异步落库，
                # 若 success 先于 running 写入，会产生一条永不更新为终态的"孤儿 running"。
                # 此处若同一调度时刻已存在终态记录（success/failed），则本次运行已正常结束，
                # 直接跳过创建 running，避免僵尸记录。
                if scheduled_naive is not None:
                    existing_terminal = await db.scheduler_executions.find_one({
                        "job_id": job_id,
                        "scheduled_time": scheduled_naive,
                        "status": {"$in": ["success", "failed"]}
                    })
                    if existing_terminal:
                        logger.debug(
                            f"ℹ️ 任务 {job_id} 调度时刻 {scheduled_naive} 已有终态记录，跳过创建 running"
                        )
                        return

            # 如果是完成状态（success/failed），优先把对应的 running 记录更新为终态
            if status in ["success", "failed"]:
                matched_running = None
                # 1) 优先按 scheduled_time 精确关联，消除按时间窗口误配（窗口≈任务周期时
                #    可能匹配到上一次运行）以及 success 先落库导致的窗口内无 running 的问题
                if scheduled_naive is not None:
                    matched_running = await db.scheduler_executions.find_one(
                        {
                            "job_id": job_id,
                            "status": "running",
                            "scheduled_time": scheduled_naive,
                        },
                        sort=[("timestamp", -1)]
                    )
                # 2) 兜底：scheduled_time 缺失（如手动触发时未携带）时退回时间窗口匹配。
                #    长期运行任务（历史同步/财务同步）使用 24h 窗口，普通任务 5 分钟
                if matched_running is None:
                    window_minutes = 24 * 60 if job_id in self.LONG_RUNNING_JOBS else 5
                    window_start = get_utc8_now() - timedelta(minutes=window_minutes)
                    matched_running = await db.scheduler_executions.find_one(
                        {
                            "job_id": job_id,
                            "status": "running",
                            "timestamp": {"$gte": window_start}
                        },
                        sort=[("timestamp", -1)]
                    )

                if matched_running:
                    # 更新现有记录
                    update_data = {
                        "status": status,
                        "execution_time": execution_time,
                        "updated_at": get_utc8_now()
                    }

                    if return_value:
                        update_data["return_value"] = return_value
                    if error_message:
                        update_data["error_message"] = error_message
                    if traceback:
                        update_data["traceback"] = traceback
                    if progress is not None:
                        update_data["progress"] = progress

                    await db.scheduler_executions.update_one(
                        {"_id": matched_running["_id"]},
                        {"$set": update_data}
                    )

                    # 记录日志
                    if status == "success":
                        logger.info(f"✅ [任务执行] {job_name} 执行成功，耗时: {execution_time:.2f}秒")
                    elif status == "failed":
                        logger.error(f"❌ [任务执行] {job_name} 执行失败: {error_message}")

                    # 处理连续失败计数和自动停用
                    await self._handle_job_failure_tracking(job_id, status)

                    return

            # 如果没有找到 running 记录，或者是 running/missed 状态，插入新记录
            execution_record = {
                "job_id": job_id,
                "job_name": job_name,
                "status": status,
                "scheduled_time": scheduled_naive,
                "execution_time": execution_time,
                "timestamp": get_utc8_now(),
                "is_manual": is_manual
            }

            if return_value:
                execution_record["return_value"] = return_value
            if error_message:
                execution_record["error_message"] = error_message
            if traceback:
                execution_record["traceback"] = traceback
            if progress is not None:
                execution_record["progress"] = progress

            await db.scheduler_executions.insert_one(execution_record)

            # 记录日志
            if status == "success":
                logger.info(f"✅ [任务执行] {job_name} 执行成功，耗时: {execution_time:.2f}秒")
            elif status == "failed":
                logger.error(f"❌ [任务执行] {job_name} 执行失败: {error_message}")
            elif status == "missed":
                logger.warning(f"⚠️ [任务执行] {job_name} 错过执行时间")
            elif status == "running":
                trigger_type = "手动触发" if is_manual else "自动触发"
                logger.info(f"🔄 [任务执行] {job_name} 开始执行 ({trigger_type})，进度: {progress}%")

            # 处理连续失败计数和自动停用
            if status in ["success", "failed"]:
                await self._handle_job_failure_tracking(job_id, status)

        except Exception as e:
            logger.error(f"❌ 记录任务执行历史失败: {e}")

    async def _handle_job_failure_tracking(self, job_id: str, status: str):
        """
        处理任务失败追踪和自动停用逻辑

        Args:
            job_id: 任务ID
            status: 执行状态 (success/failed)
        """
        try:
            self._get_db()

            # 获取任务的元数据
            metadata = await self._get_job_metadata(job_id)
            if not metadata:
                metadata = {}

            # 获取当前失败计数
            consecutive_failures = metadata.get("consecutive_failures", 0)
            max_consecutive_failures = metadata.get("max_consecutive_failures", 3)

            if status == "success":
                # 成功执行，重置失败计数
                if consecutive_failures > 0:
                    await self._update_job_metadata_field(job_id, "consecutive_failures", 0)
                    await self._update_job_metadata_field(job_id, "last_success_at", get_utc8_now())
                    logger.info(f"✅ 任务 {job_id} 执行成功，失败计数已重置")
            elif status == "failed":
                # 执行失败，增加失败计数
                consecutive_failures += 1
                await self._update_job_metadata_field(job_id, "consecutive_failures", consecutive_failures)
                await self._update_job_metadata_field(job_id, "last_failure_at", get_utc8_now())

                logger.warning(f"⚠️ 任务 {job_id} 执行失败，当前连续失败次数: {consecutive_failures}/{max_consecutive_failures}")

                # 检查是否达到自动停用阈值
                if consecutive_failures >= max_consecutive_failures:
                    # 暂停任务
                    self.scheduler.pause_job(job_id)
                    await self._record_job_action(job_id, "auto_disable", "success", f"连续失败 {consecutive_failures} 次，自动停用")
                    await self._update_job_metadata_field(job_id, "enabled", False)
                    logger.warning(f"⛔ 任务 {job_id} 连续失败 {consecutive_failures} 次，已自动停用")
                    logger.error(
                        f"🚨 任务 {job_id} 连续失败 {consecutive_failures} 次，已自动停用！"
                        f"请检查任务配置和数据源状态。"
                    )

        except Exception as e:
            logger.error(f"❌ 处理任务失败追踪失败: {e}")

    async def _update_job_metadata_field(self, job_id: str, field: str, value: Any):
        """
        更新任务的元数据字段

        Args:
            job_id: 任务ID
            field: 字段名
            value: 字段值
        """
        try:
            db = self._get_db()
            await db.scheduler_metadata.update_one(
                {"job_id": job_id},
                {"$set": {field: value, "updated_at": get_utc8_now()}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"❌ 更新任务 {job_id} 元数据字段 {field} 失败: {e}")

    async def get_user_portfolio_context(self, user_id: str) -> dict[str, Any] | None:
        """
        获取用户的持仓上下文

        Args:
            user_id: 用户ID

        Returns:
            持仓上下文字典，包含持仓列表
        """
        try:
            from app.services.portfolio_service import portfolio_service

            positions = await portfolio_service.get_positions(user_id)

            if not positions:
                return None

            # 转换为持仓上下文格式
            portfolio_context = {
                "positions": [
                    {
                        "symbol": pos.get("symbol"),
                        "stock_name": pos.get("stock_name"),
                        "quantity": pos.get("quantity"),
                        "cost_price": pos.get("cost_price"),
                        "position_ratio": pos.get("position_ratio"),
                        "buy_date": pos.get("buy_date")
                    }
                    for pos in positions
                ],
                "total_positions": len(positions)
            }

            logger.info(f"📊 获取用户 {user_id} 持仓上下文: {len(positions)} 只股票")
            return portfolio_context

        except Exception as e:
            logger.error(f"❌ 获取用户 {user_id} 持仓上下文失败: {e}")
            return None

    async def get_job_portfolio_context(self, job_id: str) -> dict[str, Any] | None:
        """
        获取任务的持仓上下文

        Args:
            job_id: 任务ID

        Returns:
            持仓上下文字典
        """
        try:
            metadata = await self._get_job_metadata(job_id)
            if metadata and metadata.get("portfolio_context"):
                return metadata.get("portfolio_context")
            return None
        except Exception as e:
            logger.error(f"❌ 获取任务 {job_id} 持仓上下文失败: {e}")
            return None

    async def update_job_portfolio_context(self, job_id: str, portfolio_context: dict[str, Any]) -> bool:
        """
        更新任务的持仓上下文

        Args:
            job_id: 任务ID
            portfolio_context: 持仓上下文

        Returns:
            是否成功
        """
        try:
            db = self._get_db()
            await db.scheduler_metadata.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "portfolio_context": portfolio_context,
                        "updated_at": get_utc8_now()
                    }
                },
                upsert=True
            )
            logger.info(f"✅ 任务 {job_id} 持仓上下文已更新")
            return True
        except Exception as e:
            logger.error(f"❌ 更新任务 {job_id} 持仓上下文失败: {e}")
            return False

    async def batch_update_jobs(
        self,
        job_ids: list[str],
        enabled: bool | None = None,
        cron_expression: str | None = None,
        reset_failures: bool = False
    ) -> dict[str, Any]:
        """
        批量更新任务

        Args:
            job_ids: 任务ID列表
            enabled: 是否启用
            cron_expression: Cron 表达式
            reset_failures: 是否重置失败计数

        Returns:
            操作结果统计
        """
        results = {
            "total": len(job_ids),
            "success": 0,
            "failed": 0,
            "errors": []
        }

        for job_id in job_ids:
            try:
                job = self.scheduler.get_job(job_id)
                if not job:
                    results["failed"] += 1
                    results["errors"].append({"job_id": job_id, "error": "任务不存在"})
                    continue

                # 更新启用/禁用状态
                if enabled is not None:
                    if enabled:
                        self.scheduler.resume_job(job_id)
                    else:
                        self.scheduler.pause_job(job_id)
                    await self._update_job_metadata_field(job_id, "enabled", enabled)
                    await self._record_job_action(job_id, "batch_update", "success", f"设置enabled={enabled}")

                # 更新 Cron 表达式
                if cron_expression:
                    from apscheduler.triggers.cron import CronTrigger

                    from app.core.config import settings
                    trigger = CronTrigger.from_crontab(cron_expression, timezone=settings.TIMEZONE)
                    self.scheduler.reschedule_job(job_id, trigger=trigger)
                    await self._update_job_metadata_field(job_id, "cron_expression", cron_expression)
                    await self._record_job_action(job_id, "batch_update", "success", f"更新cron表达式: {cron_expression}")

                # 重置失败计数
                if reset_failures:
                    await self._update_job_metadata_field(job_id, "consecutive_failures", 0)
                    await self._record_job_action(job_id, "batch_update", "success", "重置失败计数")

                results["success"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"job_id": job_id, "error": str(e)})
                logger.error(f"❌ 批量更新任务 {job_id} 失败: {e}")

        logger.info(f"✅ 批量更新任务完成: 成功 {results['success']}/{results['total']}")
        return results

    async def batch_delete_jobs(self, job_ids: list[str]) -> dict[str, Any]:
        """
        批量删除任务

        Args:
            job_ids: 任务ID列表

        Returns:
            操作结果统计
        """
        results = {
            "total": len(job_ids),
            "success": 0,
            "failed": 0,
            "errors": []
        }

        for job_id in job_ids:
            try:
                job = self.scheduler.get_job(job_id)
                if not job:
                    results["failed"] += 1
                    results["errors"].append({"job_id": job_id, "error": "任务不存在"})
                    continue

                # 移除任务
                self.scheduler.remove_job(job_id)

                # 删除元数据
                db = self._get_db()
                await db.scheduler_metadata.delete_many({"job_id": job_id})

                results["success"] += 1
                logger.info(f"✅ 批量删除任务 {job_id} 成功")

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"job_id": job_id, "error": str(e)})
                logger.error(f"❌ 批量删除任务 {job_id} 失败: {e}")

        logger.info(f"✅ 批量删除任务完成: 成功 {results['success']}/{results['total']}")
        return results

    async def batch_trigger_jobs(
        self,
        job_ids: list[str],
        kwargs: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        批量触发任务

        Args:
            job_ids: 任务ID列表
            kwargs: 传递给任务函数的参数

        Returns:
            操作结果统计
        """
        results = {
            "total": len(job_ids),
            "success": 0,
            "failed": 0,
            "errors": []
        }

        for job_id in job_ids:
            try:
                success = await self.trigger_job(job_id, kwargs=kwargs)
                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({"job_id": job_id, "error": "触发失败"})
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"job_id": job_id, "error": str(e)})
                logger.error(f"❌ 批量触发任务 {job_id} 失败: {e}")

        logger.info(f"✅ 批量触发任务完成: 成功 {results['success']}/{results['total']}")
        return results

    async def create_jobs_from_favorites(
        self,
        user_id: str,
        task_type: str = "analysis",
        cron_expression: str = "0 9 * * 1-5",
        analysis_type: str = "comprehensive",
        tags: list[str] | None = None,
        include_portfolio_context: bool = True
    ) -> dict[str, Any]:
        """
        从自选股批量创建定时任务

        Args:
            user_id: 用户ID
            task_type: 任务类型
            cron_expression: Cron 表达式
            analysis_type: 分析类型
            tags: 自选股标签过滤
            include_portfolio_context: 是否包含持仓上下文

        Returns:
            创建结果统计
        """
        try:
            # 获取用户的自选股
            from app.services.favorites_service import favorites_service
            favorites = await favorites_service.get_user_favorites(user_id)

            if not favorites:
                return {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "errors": ["用户没有自选股"]
                }

            # 根据标签过滤
            if tags:
                favorites = [f for f in favorites if any(t in f.get("tags", []) for t in tags)]

            if not favorites:
                return {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "errors": ["没有匹配标签的自选股"]
                }

            # 获取持仓上下文
            portfolio_context = None
            if include_portfolio_context:
                portfolio_context = await self.get_user_portfolio_context(user_id)

            results = {
                "total": len(favorites),
                "success": 0,
                "failed": 0,
                "created_job_ids": [],
                "errors": []
            }

            # 为每只自选股创建定时任务
            for fav in favorites:
                try:
                    stock_code = fav.get("stock_code") or fav.get("symbol")
                    stock_name = fav.get("stock_name")

                    if not stock_code:
                        results["failed"] += 1
                        results["errors"].append({"stock": stock_name, "error": "股票代码无效"})
                        continue

                    # 生成任务ID
                    job_id = f"fav_analysis_{stock_code}_{int(now_tz().timestamp())}"

                    # 构建任务参数
                    job_kwargs = {
                        "symbols": [stock_code],
                        "analysis_type": analysis_type,
                        "user_id": user_id
                    }

                    # 添加持仓上下文
                    if portfolio_context and "positions" in portfolio_context:
                        # 找到该股票对应的持仓
                        position = next(
                            (p for p in portfolio_context["positions"] if p.get("symbol") == stock_code),
                            None
                        )
                        if position:
                            job_kwargs["portfolio_context"] = {
                                "positions": [position]
                            }

                    # 创建定时任务
                    # 注意：这里只是记录任务信息到元数据集合，实际任务创建需要调度器支持
                    db = self._get_db()
                    task_metadata = {
                        "job_id": job_id,
                        "name": f"自选股分析-{stock_name}",
                        "task_type": task_type,
                        "cron_expression": cron_expression,
                        "symbols": [stock_code],
                        "params": job_kwargs,
                        "display_name": f"分析 {stock_name}",
                        "description": f"自选股 {stock_name} ({stock_code}) 的定期分析任务",
                        "enabled": True,
                        "consecutive_failures": 0,
                        "max_consecutive_failures": 3,
                        "user_id": user_id,
                        "created_at": get_utc8_now(),
                        "updated_at": get_utc8_now()
                    }

                    if portfolio_context:
                        task_metadata["portfolio_context"] = portfolio_context

                    await db.scheduler_metadata.update_one(
                        {"job_id": job_id},
                        {"$set": task_metadata},
                        upsert=True
                    )

                    results["success"] += 1
                    results["created_job_ids"].append(job_id)
                    logger.info(f"✅ 从自选股创建任务成功: {stock_name} ({stock_code}) -> {job_id}")

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({"stock": fav.get("stock_name"), "error": str(e)})
                    logger.error(f"❌ 从自选股创建任务失败: {fav.get('stock_name')} - {e}")

            logger.info(f"✅ 从自选股批量创建任务完成: 成功 {results['success']}/{results['total']}")
            return results

        except Exception as e:
            logger.error(f"❌ 从自选股批量创建任务失败: {e}")
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "errors": [str(e)]
            }

    async def _record_job_action(
        self,
        job_id: str,
        action: str,
        status: str,
        error_message: str = None
    ):
        """
        记录任务操作历史

        Args:
            job_id: 任务ID
            action: 操作类型 (pause/resume/trigger)
            status: 状态 (success/failed)
            error_message: 错误信息
        """
        try:
            db = self._get_db()
            await db.scheduler_history.insert_one({
                "job_id": job_id,
                "action": action,
                "status": status,
                "error_message": error_message,
                "timestamp": get_utc8_now()
            })
        except Exception as e:
            logger.error(f"❌ 记录任务操作历史失败: {e}")

    async def _get_job_metadata(self, job_id: str) -> dict[str, Any] | None:
        """
        获取任务元数据（触发器名称和备注）

        Args:
            job_id: 任务ID

        Returns:
            元数据字典，如果不存在则返回None
        """
        try:
            db = self._get_db()
            metadata = await db.scheduler_metadata.find_one({"job_id": job_id})
            if metadata:
                metadata.pop("_id", None)
                return metadata
            return None
        except Exception as e:
            logger.error(f"❌ 获取任务 {job_id} 元数据失败: {e}")
            return None

    async def update_job_metadata(
        self,
        job_id: str,
        display_name: str | None = None,
        description: str | None = None
    ) -> bool:
        """
        更新任务元数据

        Args:
            job_id: 任务ID
            display_name: 触发器名称
            description: 备注

        Returns:
            是否成功
        """
        try:
            # 检查任务是否存在
            job = self.scheduler.get_job(job_id)
            if not job:
                logger.error(f"❌ 任务 {job_id} 不存在")
                return False

            db = self._get_db()
            update_data = {
                "job_id": job_id,
                "updated_at": get_utc8_now()
            }

            if display_name is not None:
                update_data["display_name"] = display_name
            if description is not None:
                update_data["description"] = description

            # 使用 upsert 更新或插入
            await db.scheduler_metadata.update_one(
                {"job_id": job_id},
                {"$set": update_data},
                upsert=True
            )

            logger.info(f"✅ 任务 {job_id} 元数据已更新")
            return True
        except Exception as e:
            logger.error(f"❌ 更新任务 {job_id} 元数据失败: {e}")
            return False


# 全局服务实例
_scheduler_service: SchedulerService | None = None
_scheduler_instance: AsyncIOScheduler | None = None


def set_scheduler_instance(scheduler: AsyncIOScheduler):
    """
    设置调度器实例
    
    Args:
        scheduler: APScheduler调度器实例
    """
    global _scheduler_instance
    _scheduler_instance = scheduler
    logger.info("✅ 调度器实例已设置")


def get_scheduler_service() -> SchedulerService:
    """
    获取调度器服务实例

    Returns:
        调度器服务实例
    """
    global _scheduler_service, _scheduler_instance

    if _scheduler_instance is None:
        raise RuntimeError("调度器实例未设置，请先调用 set_scheduler_instance()")

    if _scheduler_service is None:
        _scheduler_service = SchedulerService(_scheduler_instance)
        logger.info("✅ 调度器服务实例已创建")

    return _scheduler_service


async def update_job_progress(
    job_id: str,
    progress: int,
    message: str = None,
    current_item: str = None,
    total_items: int = None,
    processed_items: int = None
):
    """
    更新任务执行进度（供定时任务内部调用）

    Args:
        job_id: 任务ID
        progress: 进度百分比（0-100）
        message: 进度消息
        current_item: 当前处理项
        total_items: 总项数
        processed_items: 已处理项数
    """
    try:
        # 使用模块级单例同步客户端，避免每次调用都新建 MongoClient
        sync_db = _get_sync_db()

        # 查找最近的执行记录
        latest_execution = sync_db.scheduler_executions.find_one(
            {"job_id": job_id, "status": {"$in": ["running", "success", "failed"]}},
            sort=[("timestamp", -1)]
        )

        if latest_execution:
            # 检查是否有取消请求
            if latest_execution.get("cancel_requested"):
                logger.warning(f"⚠️ 任务 {job_id} 收到取消请求，即将停止")
                raise TaskCancelledException(f"任务 {job_id} 已被用户取消")

            # 更新现有记录
            update_data = {
                "progress": progress,
                "status": "running",
                "updated_at": get_utc8_now()
            }

            if message:
                update_data["progress_message"] = message
            if current_item:
                update_data["current_item"] = current_item
            if total_items is not None:
                update_data["total_items"] = total_items
            if processed_items is not None:
                update_data["processed_items"] = processed_items

            sync_db.scheduler_executions.update_one(
                {"_id": latest_execution["_id"]},
                {"$set": update_data}
            )
        else:
            # 创建新的执行记录（任务刚开始）
            # 获取任务名称
            job_name = job_id
            if _scheduler_instance:
                job = _scheduler_instance.get_job(job_id)
                if job:
                    job_name = job.name

            execution_record = {
                "job_id": job_id,
                "job_name": job_name,
                "status": "running",
                "progress": progress,
                "scheduled_time": get_utc8_now(),
                "timestamp": get_utc8_now()
            }

            if message:
                execution_record["progress_message"] = message
            if current_item:
                execution_record["current_item"] = current_item
            if total_items is not None:
                execution_record["total_items"] = total_items
            if processed_items is not None:
                execution_record["processed_items"] = processed_items

            sync_db.scheduler_executions.insert_one(execution_record)

        # 不再 close()：使用模块级单例客户端，由进程生命周期管理

    except Exception as e:
        logger.error(f"❌ 更新任务进度失败: {e}")

