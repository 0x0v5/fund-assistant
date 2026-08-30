"""容器内定时调度（替代 Hermes cron）.

设计目标：项目部署到 Docker 后不再依赖任何外部 agent，
由本进程内的 APScheduler 调度 3 个抓取+推送任务。

3 个任务（默认时区 Asia/Shanghai，工作日）：
- qdii_daily          10:00  QDII 场外限额
- etf_momentum        14:30  ETF 双动量轮动
- industry_ranking    15:30  行业板块涨跌榜

misfire_grace_time=300s：后端重启或卡住 5 分钟内能补上。
coalesce=True：多次堆积合并成一次。
max_instances=1：同一任务永不并发。

环境变量：
- SCHEDULER_ENABLED   默认 true；设为 false 关闭（手动测试场景）
- SCHEDULER_TIMEZONE  默认 Asia/Shanghai
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes")
TIMEZONE = os.environ.get("SCHEDULER_TIMEZONE", "Asia/Shanghai")

# (job_id, 脚本模块名, 入口函数名, day_of_week, hour, minute)
JOBS = [
    ("qdii_daily",       "fetch_qdii",      "run", "mon-fri", 10, 0),
    ("etf_momentum",     "run_momentum",    "run", "mon-fri", 14, 30),
    ("industry_ranking", "industry_ranking", "run", "mon-fri", 15, 30),
]

_scheduler: Optional[AsyncIOScheduler] = None


def _ensure_scripts_on_path() -> None:
    """把 scripts/ 加到 sys.path，使 fetch_qdii / feishu_sender 等可 import。

    backend/app/services/scheduler.py 在 backend/ 进程内运行，
    脚本文件位于 <project_root>/scripts/。
    """
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
    scripts_dir = os.path.join(project_root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def _load_run_fn(module_name: str, fn_name: str):
    """动态加载 scripts.<module>.<fn>，失败返回 None。"""
    _ensure_scripts_on_path()
    try:
        mod = __import__(module_name)
    except Exception as e:
        logger.error(f"[scheduler] 加载 scripts.{module_name} 失败: {e}")
        return None
    fn = getattr(mod, fn_name, None)
    if fn is None:
        logger.error(f"[scheduler] scripts.{module_name} 没有 {fn_name}() 函数")
    return fn


async def _safe_run(job_id: str, run_fn) -> None:
    """执行 job，捕获异常不让 APScheduler 进入 ERROR 状态。"""
    logger.info(f"[scheduler] 开始执行 {job_id}")
    try:
        result = run_fn()
        if asyncio.iscoroutine(result):
            result = await result
        logger.info(f"[scheduler] {job_id} 完成: ok={result}")
    except Exception as e:
        logger.error(f"[scheduler] {job_id} 异常: {e}\n{traceback.format_exc()}")


def _make_job_coro(job_id: str, run_fn):
    """为每个 job 生成独立的闭包，让 job.func 不等于 _safe_run 本身。

    避免手动触发时把 _safe_run 当成 run_fn 递归调用。
    """
    async def _job():
        await _safe_run(job_id, run_fn)
    return _job


def start() -> None:
    """启动 scheduler（非异步）。lifespan 里同步调用即可。"""
    global _scheduler
    if not SCHEDULER_ENABLED:
        logger.info("[scheduler] SCHEDULER_ENABLED=false，跳过启动")
        return
    if _scheduler is not None:
        logger.warning("[scheduler] 已在运行，跳过重复启动")
        return

    _scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    for job_id, module_name, fn_name, dow, hour, minute in JOBS:
        run_fn = _load_run_fn(module_name, fn_name)
        if run_fn is None:
            continue
        _scheduler.add_job(
            _make_job_coro(job_id, run_fn),
            CronTrigger(day_of_week=dow, hour=hour, minute=minute, timezone=TIMEZONE),
            id=job_id,
            name=f"{job_id} ({dow} {hour:02d}:{minute:02d} {TIMEZONE})",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            f"[scheduler] 注册 {job_id}  cron='{dow} {hour:02d}:{minute:02d}' tz={TIMEZONE}"
        )

    _scheduler.start()
    logger.info(f"[scheduler] 已启动，共 {len(_scheduler.get_jobs())} 个任务")


def stop() -> None:
    """停止 scheduler。lifespan 退出时调用。"""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception as e:
        logger.warning(f"[scheduler] 关闭异常: {e}")
    finally:
        _scheduler = None
        logger.info("[scheduler] 已停止")


def get_jobs() -> list[dict]:
    """给 /api/scheduler/status 用。"""
    if _scheduler is None:
        return []
    out = []
    for job in _scheduler.get_jobs():
        out.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return out


def trigger_now(job_id: str) -> dict:
    """手动立即执行指定任务（异步后台执行，不阻塞 HTTP 响应）。

    Returns:
        {success, job_id} 或 {success:false, error}
    """
    if _scheduler is None:
        return {"success": False, "error": "scheduler 未启动（SCHEDULER_ENABLED=false）"}
    job = _scheduler.get_job(job_id)
    if job is None:
        return {"success": False, "error": f"任务不存在：{job_id}"}

    # job.func 是 _make_job_coro 返回的闭包，直接无参调用即可
    asyncio.create_task(job.func())
    return {"success": True, "job_id": job_id, "next_run": job.next_run_time.isoformat() if job.next_run_time else None}
