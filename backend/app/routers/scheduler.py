"""APScheduler 状态查询与手动触发 API.

端点：
- GET  /api/scheduler/status  列出所有任务和下次执行时间
- POST /api/scheduler/run/{job_id}  立即触发指定任务（不等 cron）
"""

from fastapi import APIRouter, HTTPException

from app.services import scheduler

router = APIRouter()


@router.get("/status")
async def scheduler_status():
    """返回调度器状态与已注册任务。

    即使 scheduler 未启动也会返回（enabled=false, jobs=[]），
    方便前端展示"是否启用"和诊断 cron 没跑的问题。
    """
    return {
        "enabled": scheduler.SCHEDULER_ENABLED,
        "timezone": scheduler.TIMEZONE,
        "running": scheduler._scheduler is not None,
        "jobs": scheduler.get_jobs(),
    }


@router.post("/run/{job_id}")
async def scheduler_run(job_id: str):
    """手动触发指定任务（异步后台执行，HTTP 立即返回）。

    用于：cron 还没到时间想验证脚本是否还能跑通；排查抓取/推送失败。
    """
    result = scheduler.trigger_now(job_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
