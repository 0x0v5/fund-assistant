"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import qdii, fund, etf, industry, backtest, activity, notify, scheduler as scheduler_router
from app.services import scheduler

# 让 scheduler/apscheduler 的 INFO 日志能输出（uvicorn 不配 root logger）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    from app.db.database import init_db
    await init_db()
    # 启动容器内调度器（替代外部 cron / Hermes）
    # SCHEDULER_ENABLED=false 时跳过；SCHEDULER_TIMEZONE 控制时区
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="选基助手 API",
    description="基金评测、QDII额度、ETF轮动策略",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(qdii.router, prefix="/api/qdii", tags=["QDII额度"])
app.include_router(fund.router, prefix="/api/fund", tags=["基金评测"])
app.include_router(etf.router, prefix="/api/etf", tags=["ETF轮动"])
app.include_router(industry.router, prefix="/api/industry", tags=["行业基金"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["基金回测"])
app.include_router(activity.router, prefix="/api/activity", tags=["最近活动"])
app.include_router(notify.router, prefix="/api/notify", tags=["飞书通知"])
app.include_router(scheduler_router.router, prefix="/api/scheduler", tags=["定时调度"])


@app.get("/")
async def root():
    return {"message": "选基助手 API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}
