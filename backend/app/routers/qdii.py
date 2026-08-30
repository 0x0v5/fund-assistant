"""QDII ETF quota API router.

架构：
- GET  /api/qdii/quota         读数据库（前端定时查看）
- POST /api/qdii/quota/refresh 触发爬虫 + 写库（cron 调度 / 手动重抓）
- GET  /api/qdii/quota/{code}  读数据库（单只基金详情）
"""

from datetime import datetime
from typing import Optional
import asyncio
from fastapi import APIRouter, HTTPException

from app.models.schemas import QdiiFund, QdiiQuotaResponse
from app.services.crawler import qdii_quota, QdiiQuotaService
from app.db.database import execute_update, execute_query

router = APIRouter()


# ============ 分类映射 ============

_CODE_TO_TYPE: dict[str, str] = {}
for _code in QdiiQuotaService.ETF_LINK_FUNDS:
    _CODE_TO_TYPE[_code] = "ETF联接基金"
for _code in QdiiQuotaService.FOF_FUNDS:
    _CODE_TO_TYPE[_code] = "FOF基金"
for _code in QdiiQuotaService.INDEX_FUNDS:
    _CODE_TO_TYPE[_code] = "股票指数/LOF"
for _code in QdiiQuotaService.NDX_ETF_LINK_FUNDS:
    _CODE_TO_TYPE[_code] = "纳指100 ETF联接"
for _code in QdiiQuotaService.NDX_DIRECT_FUNDS:
    _CODE_TO_TYPE[_code] = "纳指100 直接指数"


def _to_fund_dict(row: dict) -> dict:
    """将数据库行转换为前端期望的字段结构。"""
    code = row.get("code", "")
    return {
        "code": code,
        "name": row.get("name", ""),
        "type": _CODE_TO_TYPE.get(code, "其他"),
        "quota_status": row.get("quota_status", ""),
        "apply_status": row.get("apply_status", ""),
        "limit_amount": row.get("limit_amount", ""),
        "redeem_status": row.get("redeem_status", ""),
        "nav_date": row.get("nav_date", ""),
        "manager": row.get("manager", ""),
        "scale": row.get("scale", ""),
        "m_fee": row.get("m_fee", ""),
        "t_fee": row.get("t_fee", ""),
        "buy_fee": row.get("buy_fee", ""),
        "redeem_fee": row.get("redeem_fee", ""),
        "update_time": row.get("update_time", ""),
    }


# ============ 核心：爬 + 写库 ============

async def crawl_and_save_qdii() -> tuple[list[dict], str]:
    """触发爬虫抓取所有 QDII 基金额度，写入数据库。"""
    funds_data = await asyncio.to_thread(qdii_quota.get_qdii_quota, force=True)
    update_time = datetime.now().isoformat()
    for fund in funds_data:
        await save_qdii_quota(fund, update_time)
    return funds_data, update_time


async def save_qdii_quota(fund: dict, update_time: str):
    """保存 QDII 额度数据到数据库"""
    try:
        await execute_update("""
            INSERT INTO qdii_quota
            (code, name, premium, quota_status, update_time,
             apply_status, limit_amount, redeem_status, nav_date,
             manager, scale, m_fee, t_fee, buy_fee, redeem_fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, update_time) DO UPDATE SET
                name = excluded.name,
                premium = excluded.premium,
                quota_status = excluded.quota_status,
                apply_status = excluded.apply_status,
                limit_amount = excluded.limit_amount,
                redeem_status = excluded.redeem_status,
                nav_date = excluded.nav_date,
                manager = excluded.manager,
                scale = excluded.scale,
                m_fee = excluded.m_fee,
                t_fee = excluded.t_fee,
                buy_fee = excluded.buy_fee,
                redeem_fee = excluded.redeem_fee
        """, (
            fund.get("code", ""),
            fund.get("name", ""),
            0,
            fund.get("quota_status", ""),
            update_time,
            fund.get("apply_status", ""),
            fund.get("limit_amount", ""),
            fund.get("redeem_status", ""),
            fund.get("nav_date", ""),
            fund.get("manager", ""),
            fund.get("scale", ""),
            fund.get("m_fee", ""),
            fund.get("t_fee", ""),
            fund.get("buy_fee", ""),
            fund.get("redeem_fee", ""),
        ))
    except Exception as e:
        print(f"保存 QDII 额度失败: {e}")


async def read_latest_qdii_from_db() -> tuple[list[dict], str]:
    """从数据库读取每个 code 的最新一条记录。"""
    rows = await execute_query("""
        SELECT q.* FROM qdii_quota q
        JOIN (
            SELECT code, MAX(update_time) AS max_update
            FROM qdii_quota
            GROUP BY code
        ) latest ON q.code = latest.code AND q.update_time = latest.max_update
        ORDER BY q.code
    """)
    funds = [_to_fund_dict(r) for r in rows]
    update_time = rows[0]["update_time"] if rows else ""
    return funds, update_time


# ============ API ============

@router.get("/quota")
async def get_qdii_quota():
    """获取所有 QDII 场外基金限额状态（从数据库读取，不触发爬虫）。"""
    try:
        funds, update_time = await read_latest_qdii_from_db()
        return {"funds": funds, "update_time": update_time}
    except Exception as e:
        print(f"读取 QDII 额度失败: {e}")
        return {"funds": [], "update_time": datetime.now().isoformat()}


@router.post("/quota/refresh")
async def refresh_quota():
    """触发爬虫抓取并写入数据库（用于 cron 定时任务或手动重抓）。"""
    try:
        funds, update_time = await crawl_and_save_qdii()
        return {
            "message": "刷新完成",
            "count": len(funds),
            "update_time": update_time,
            "funds": funds,
        }
    except Exception as e:
        print(f"刷新 QDII 额度失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quota/history")
async def get_qdii_quota_history(code: Optional[str] = None, days: int = 30):
    """获取 QDII 额度历史记录"""
    try:
        if code:
            rows = await execute_query("""
                SELECT * FROM qdii_quota
                WHERE code = ? AND update_time >= date('now', ?)
                ORDER BY update_time DESC
            """, (code, f'-{days} days'))
        else:
            rows = await execute_query("""
                SELECT * FROM qdii_quota
                WHERE update_time >= date('now', ?)
                ORDER BY update_time DESC
            """, (f'-{days} days',))
        return {"data": rows}
    except Exception as e:
        print(f"获取历史记录失败: {e}")
        return {"data": []}


@router.get("/quota/etf_link")
async def get_etf_link_quota():
    """获取ETF联接基金限额状态（从数据库读）。"""
    funds, update_time = await read_latest_qdii_from_db()
    return {"funds": [f for f in funds if f["type"] == "ETF联接基金"], "update_time": update_time}


@router.get("/quota/fof")
async def get_fof_quota():
    """获取FOF基金限额状态（从数据库读）。"""
    funds, update_time = await read_latest_qdii_from_db()
    return {"funds": [f for f in funds if f["type"] == "FOF基金"], "update_time": update_time}


@router.get("/quota/index")
async def get_index_quota():
    """获取股票指数/LOF基金限额状态（从数据库读）。"""
    funds, update_time = await read_latest_qdii_from_db()
    return {"funds": [f for f in funds if f["type"] == "股票指数/LOF"], "update_time": update_time}


@router.get("/quota/ndx_etf_link")
async def get_ndx_etf_link_quota():
    """获取纳斯达克100 ETF联接基金限额状态（从数据库读）。"""
    funds, update_time = await read_latest_qdii_from_db()
    return {"funds": [f for f in funds if f["type"] == "纳指100 ETF联接"], "update_time": update_time}


@router.get("/quota/ndx_direct")
async def get_ndx_direct_quota():
    """获取纳斯达克100 直接指数QDII限额状态（从数据库读）。"""
    funds, update_time = await read_latest_qdii_from_db()
    return {"funds": [f for f in funds if f["type"] == "纳指100 直接指数"], "update_time": update_time}


@router.get("/quota/{fund_code}", response_model=QdiiFund)
async def get_qdii_quota_detail(fund_code: str):
    """获取单个 QDII 基金限额详情（从数据库读）。"""
    rows = await execute_query("""
        SELECT * FROM qdii_quota
        WHERE code = ?
        ORDER BY update_time DESC
        LIMIT 1
    """, (fund_code,))

    if not rows:
        raise HTTPException(status_code=404, detail="基金不存在或尚未抓取")

    row = rows[0]
    return QdiiFund(
        code=row["code"],
        name=row["name"],
        premium=0,
        quota_status=row.get("quota_status", ""),
        last_update=datetime.fromisoformat(row["update_time"]),
    )