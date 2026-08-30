"""ETF momentum rotation strategy API router.

架构：
- GET  /api/etf/momentum           读数据库，按 strategy 重算 combined_score / signal
- POST /api/etf/momentum/refresh   触发计算 + 写库（cron 调度 / 手动更新）
- GET  /api/etf/detail/{code}      读数据库
- GET  /api/etf/candidates         静态配置
- GET  /api/etf/history            历史记录
"""

from __future__ import annotations  # 类型注解懒求值，pandas 可懒加载

from datetime import datetime
from typing import Optional
import asyncio
from fastapi import APIRouter, HTTPException

from app.models.schemas import EtfSignal, EtfMomentum
from app.services.crawler import fund_data
from app.db.database import execute_update, execute_query, execute_many

router = APIRouter()

# 用户指定的 ETF 标的（双动量轮动）
_MOMENTUM_ETFS = [
    {"code": "159915", "name": "创业板ETF", "type": "国内"},
    {"code": "512890", "name": "红利低波ETF", "type": "红利"},
    {"code": "159941", "name": "纳指ETF", "type": "美股"},
    {"code": "518880", "name": "黄金ETF", "type": "黄金"},
]


def _compute_signal(combined: float, above_ma60: bool, factor_type: str = "return") -> str:
    """根据综合评分和 60 日线状态判定信号。

    长期趋势统一用「当前价格是否大于 60 日线」过滤：
    - above_ma60 = True  → 在 60 日线上方，允许买入/持有
    - above_ma60 = False → 在 60 日线下方，直接卖出/观望

    factor_type:
    - return: 涨跌幅模式，buy 阈值 = 3（与历史一致）
    - sharpe: 夏普比率模式，buy 阈值 = 0（与策略回测 factor_type=sharpe 一致）
    """
    buy_threshold = 0 if factor_type == "sharpe" else 3
    if above_ma60 and combined > buy_threshold:
        return "buy"
    elif above_ma60:
        return "hold"
    return "sell"


def _row_to_signal(row: dict, strategy: str) -> EtfSignal:
    """把数据库行转 EtfSignal，combined_score 按 strategy 实时计算。

    - aggressive: 综合评分 = 100% 短期涨幅（20 日），阈值 > 3
    - conservative: 综合评分 = 20 日夏普比率，阈值 > 0
      （与策略回测 factor_type=sharpe 完全对齐）
    """
    short_m = row.get("short_momentum") or 0
    medium_m = row.get("medium_momentum") or 0
    short_sharpe = row.get("short_sharpe") or 0
    if strategy == "aggressive":
        combined = short_m * 1.0 + medium_m * 0.0
        factor_type = "return"
    else:
        combined = short_sharpe
        factor_type = "sharpe"

    above_ma60 = bool(row.get("above_ma60"))
    signal = _compute_signal(combined, above_ma60, factor_type)

    return EtfSignal(
        code=row["code"],
        name=row.get("name", ""),
        short_momentum=short_m,
        medium_momentum=medium_m,
        combined_score=round(combined, 2),
        signal=signal,
        daily_change=row.get("daily_change") or 0,
        current_price=row.get("current_price") or 0,
        above_ma60=above_ma60,
        update_date=row.get("calc_time", "")[:10] if row.get("calc_time") else "",
    )


async def _read_latest_from_db() -> tuple[list[EtfSignal], str]:
    """读取每个 ETF 最新一条动量记录。

    用 MAX(id) 而不是 MAX(calc_time)：id 是自增主键单调递增，
    不受系统时钟回拨影响，能正确选出"最近一次成功写入"的行。
    """
    rows = await execute_query("""
        SELECT m.* FROM momentum_history m
        JOIN (
            SELECT code, MAX(id) AS max_id
            FROM momentum_history
            GROUP BY code
        ) latest ON m.id = latest.max_id
    """)
    update_time = rows[0]["calc_time"] if rows else ""
    signals = [_row_to_signal(r, "aggressive") for r in rows]
    return signals, update_time


async def _read_second_latest_top_code() -> Optional[str]:
    """读 DB 中"上一次"刷新时排名第一的 ETF code（用于生成切换建议）。

    用 MAX(id) 而不是 calc_time：不受系统时钟回拨影响。
    步骤：
      1. 找每个 ETF 的"最新行 id"集合（共 N 条，对应当前最新一次刷新）；
      2. 取其中最小的 id 视为当前批次起点；
      3. 比这个起点 id 更小的最新行集 = 上一次刷新批次。
    """
    # 当前每个 ETF 的最新行 id 集合
    latest_ids = await execute_query("""
        SELECT MAX(id) AS max_id FROM momentum_history GROUP BY code
    """)
    if len(latest_ids) < 2:
        return None
    # 当前批次中"最早写入"的 id；上一次刷新批次的 id 都 < 这个值
    latest_ids_sorted = sorted(r["max_id"] for r in latest_ids)
    cursor_id = latest_ids_sorted[0]
    rows2 = await execute_query("""
        SELECT m.code, m.name, m.short_momentum, m.medium_momentum, m.above_ma60
        FROM momentum_history m
        JOIN (
            SELECT code, MAX(id) AS max_id
            FROM momentum_history
            WHERE id < ?
            GROUP BY code
        ) prev ON m.id = prev.max_id
    """, (cursor_id,))
    if not rows2:
        return None
    candidates = [_row_to_signal(r, "aggressive") for r in rows2]
    candidates.sort(key=lambda x: x.combined_score, reverse=True)
    return candidates[0].code if candidates else None


# ============ API ============

@router.get("/momentum", response_model=EtfMomentum)
async def get_momentum(strategy: str = "aggressive"):
    """获取 ETF 双动量轮动信号（从数据库读取，按 strategy 重算）。"""
    signals, update_time = await _read_latest_from_db()

    # 按 strategy 重算 combined_score 和 signal（用 MAX(id) 选最新行，不受时钟回拨影响）
    candidates = []
    for row in await execute_query("""
        SELECT m.* FROM momentum_history m
        JOIN (
            SELECT code, MAX(id) AS max_id
            FROM momentum_history
            GROUP BY code
        ) latest ON m.id = latest.max_id
    """):
        candidates.append(_row_to_signal(row, strategy))

    # 按综合评分排序
    candidates.sort(key=lambda x: x.combined_score, reverse=True)
    top_etf = candidates[0] if candidates else None

    # 切换建议：对比上次刷新时的 top
    switch_suggestion = None
    prev_top_code = await _read_second_latest_top_code()
    if prev_top_code and top_etf and top_etf.code != prev_top_code:
        old_etf = next((c for c in candidates if c.code == prev_top_code), None)
        if old_etf and top_etf.signal != "sell":
            switch_suggestion = f"🔄 建议切换: {old_etf.name} → {top_etf.name}"
        elif old_etf and top_etf.signal == "sell":
            switch_suggestion = f"⚠️ {top_etf.name} 在60日线下，暂不切换"

    # 信号文案
    if top_etf:
        if top_etf.signal == "sell":
            signal_text = f"⚠️ {top_etf.name} 在60日线下方，建议观望"
        elif switch_suggestion:
            signal_text = f"📌 建议满仓: {top_etf.name}"
        else:
            signal_text = f"📌 继续持有: {top_etf.name}"
    else:
        signal_text = "所有标的均在60日线下方，建议观望"

    return EtfMomentum(
        strategy=strategy,
        signal=signal_text,
        holdings=[top_etf] if top_etf and top_etf.signal != "sell" else [],
        candidates=candidates,
        last_update=datetime.fromisoformat(update_time) if update_time else datetime.now(),
        switch_suggestion=switch_suggestion,
    )


async def _save_etf_nav_to_fund_nav(code: str, df) -> int:
    """把新浪 ETF 日 K 收盘价同步到 fund_nav 表。

    - nav = 原始收盘价（实际交易价格）
    - accumulated_nav = 后复权收盘价（自动处理份额拆分/合并，保持收益连续）

    数据校验：
    - 跳过周末/非交易日（weekday >= 5）
    - 对收盘价做拆分调整，使 accumulated_nav 在拆分点保持连续
    """
    import pandas as pd  # lazy：仅 ETF 刷新时加载
    if df is None or df.empty:
        return 0

    try:
        new_rows = df.copy()
        new_rows["date"] = pd.to_datetime(new_rows["date"])
        # 仅处理交易日（跳过周末）
        new_rows = new_rows[new_rows["date"].dt.weekday < 5]
        new_rows = new_rows.sort_values("date")
        if new_rows.empty:
            return 0

        prices = pd.Series(new_rows["close"].values, index=new_rows["date"])
        adjusted = fund_data.adjust_for_splits(prices)

        nav_records = []
        for date, close in prices.items():
            date_str = date.strftime("%Y-%m-%d")
            accumulated = round(float(adjusted.loc[date]), 4)
            nav_records.append((code, date_str, float(close), accumulated))

        if nav_records:
            await execute_many(
                """
                INSERT OR REPLACE INTO fund_nav (code, date, nav, accumulated_nav)
                VALUES (?, ?, ?, ?)
                """,
                nav_records,
            )

        return len(nav_records)
    except Exception as e:
        print(f"同步 ETF {code} 净值到 fund_nav 失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


@router.post("/momentum/refresh")
async def refresh_momentum():
    """触发计算 4 只 ETF 的动量指标并写入数据库；同时把收盘价同步到 fund_nav。"""
    try:
        calc_time = datetime.now().isoformat()
        results = []
        for etf in _MOMENTUM_ETFS:
            code = etf["code"]
            name = etf["name"]
            momentum_data = await asyncio.to_thread(fund_data.calc_momentum, code, short_window=20, long_window=60)
            # 数据源失败时 calc_momentum 返回 current_price=0 / update_date=None
            # 此时跳过写入，保留 DB 里上一次成功的结果，避免全 0 占位行污染
            if not momentum_data.get("update_date") or momentum_data.get("current_price", 0) <= 0:
                print(f"[{code}] 数据源失败，跳过本次刷新")
                results.append({
                    "code": code, "name": name, "status": "skipped",
                    "reason": "K线接口无有效数据",
                })
                continue
            short_m = momentum_data["short_momentum"]
            long_m = momentum_data["long_momentum"]
            short_sharpe = momentum_data.get("short_sharpe", 0)
            above_ma60 = momentum_data["above_ma60"]
            # 默认用日 K 接口算的 daily_change（昨日收盘 vs 前日收盘）
            daily_change = momentum_data.get("daily_change", 0)
            current_price = momentum_data.get("current_price", 0)

            # 优先用实时盘中行情覆盖 daily_change + current_price
            # 这样 cron 14:30 推送时拿到的是「今日盘中」涨跌，而不是「昨日收盘」
            try:
                rt = await asyncio.to_thread(fund_data.get_etf_realtime, code)
                if rt and rt.get("is_trading") and rt.get("current_price", 0) > 0:
                    daily_change = rt["change_pct"]
                    current_price = rt["current_price"]
                    print(f"[{code}] 盘中实时: 现价={current_price} 涨跌={daily_change:+.2f}% (更新于 {rt['update_time']})")
                else:
                    print(f"[{code}] 非交易时段，沿用日 K 数据: 涨跌={daily_change:+.2f}%")
            except Exception as e:
                print(f"[{code}] 实时接口失败，沿用日 K 数据: {e}")

            # 默认按 aggressive 写入 combined_score 和 signal（GET 时按 strategy 重算）
            combined = short_m * 1.0 + long_m * 0.0
            signal = _compute_signal(combined, above_ma60, factor_type="return")

            await save_momentum_history(code, name, short_m, long_m,
                                         round(combined, 2), signal, calc_time,
                                         daily_change, current_price, above_ma60,
                                         short_sharpe)

            # 同步日 K 收盘价到 fund_nav
            hist_df = await asyncio.to_thread(fund_data.get_etf_hist, code, days=90)
            nav_saved = await _save_etf_nav_to_fund_nav(code, hist_df)

            results.append({
                "code": code, "name": name,
                "short_momentum": short_m, "medium_momentum": long_m,
                "short_sharpe": short_sharpe,
                "combined_score": round(combined, 2),
                "signal": signal,
                "daily_change": daily_change,
                "current_price": current_price,
                "update_date": momentum_data.get("update_date", ""),
                "nav_saved": nav_saved,
            })

        return {
            "message": "刷新完成",
            "count": len(results),
            "update_time": calc_time,
            "results": results,
        }
    except Exception as e:
        print(f"刷新 ETF 动量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def save_momentum_history(code: str, name: str, short_m: float, medium_m: float,
                                  combined_score: float, signal: str, calc_time: str,
                                  daily_change: float, current_price: float, above_ma60: bool,
                                  short_sharpe: float = 0):
    """保存动量数据到数据库。

    保留历史：每条记录独立写入；GET 接口用 MAX(id) 而不是 MAX(calc_time)，
    这样即使系统时钟回拨也不会让旧的（calc_time 看起来"更晚"）记录当选。
    """
    try:
        await execute_update("""
            INSERT INTO momentum_history
            (code, name, short_momentum, medium_momentum, short_sharpe, combined_score,
             signal, calc_time, daily_change, current_price, above_ma60)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, name, short_m, medium_m, short_sharpe, combined_score,
              signal, calc_time, daily_change, current_price, int(above_ma60)))
    except Exception as e:
        print(f"保存动量数据失败: {e}")


@router.get("/compare-sources")
async def compare_sources(strategy: str = "aggressive"):
    """对比新浪与腾讯数据源计算的动量指标差异。"""
    results = []
    for etf in _MOMENTUM_ETFS:
        code = etf["code"]
        name = etf["name"]
        sina = await asyncio.to_thread(fund_data.calc_momentum, code)
        tencent = await asyncio.to_thread(fund_data.calc_momentum_tencent, code)

        sina_signal = _compute_signal(
            sina["short_momentum"] if strategy == "aggressive" else sina["short_sharpe"],
            sina["above_ma60"],
            "return" if strategy == "aggressive" else "sharpe",
        )
        tencent_signal = _compute_signal(
            tencent["short_momentum"] if strategy == "aggressive" else tencent["short_sharpe"],
            tencent["above_ma60"],
            "return" if strategy == "aggressive" else "sharpe",
        )

        results.append({
            "code": code,
            "name": name,
            "strategy": strategy,
            "sina": {
                "short_momentum": sina["short_momentum"],
                "medium_momentum": sina["long_momentum"],
                "short_sharpe": sina["short_sharpe"],
                "combined_score": round(sina["short_momentum"], 2) if strategy == "aggressive" else round(sina["short_sharpe"], 2),
                "signal": sina_signal,
                "above_ma60": sina["above_ma60"],
                "current_price": sina["current_price"],
                "daily_change": sina["daily_change"],
                "update_date": sina["update_date"],
            },
            "tencent": {
                "short_momentum": tencent["short_momentum"],
                "medium_momentum": tencent["long_momentum"],
                "short_sharpe": tencent["short_sharpe"],
                "combined_score": round(tencent["short_momentum"], 2) if strategy == "aggressive" else round(tencent["short_sharpe"], 2),
                "signal": tencent_signal,
                "above_ma60": tencent["above_ma60"],
                "current_price": tencent["current_price"],
                "daily_change": tencent["daily_change"],
                "update_date": tencent["update_date"],
            },
            "diff": {
                "short_momentum": round(sina["short_momentum"] - tencent["short_momentum"], 4),
                "medium_momentum": round(sina["long_momentum"] - tencent["long_momentum"], 4),
                "short_sharpe": round(sina["short_sharpe"] - tencent["short_sharpe"], 4),
                "current_price": round(sina["current_price"] - tencent["current_price"], 4),
                "daily_change": round(sina["daily_change"] - tencent["daily_change"], 4),
            },
            "consistent": sina_signal == tencent_signal and abs(sina["short_momentum"] - tencent["short_momentum"]) < 0.1,
        })

    return {
        "strategy": strategy,
        "update_time": datetime.now().isoformat(),
        "results": results,
    }


@router.get("/candidates")
async def get_candidates():
    """获取候选 ETF 列表."""
    return {"candidates": _MOMENTUM_ETFS}


@router.get("/history")
async def get_momentum_history(code: str = None, days: int = 30):
    """获取历史动量记录"""
    try:
        if code:
            rows = await execute_query("""
                SELECT * FROM momentum_history
                WHERE code = ?
                ORDER BY calc_time DESC
                LIMIT ?
            """, (code, days))
        else:
            rows = await execute_query("""
                SELECT * FROM momentum_history
                ORDER BY calc_time DESC
                LIMIT ?
            """, (days,))
        return {"data": rows}
    except Exception as e:
        print(f"获取历史记录失败: {e}")
        return {"data": []}


@router.get("/detail/{code}")
async def get_etf_detail(code: str):
    """获取单个 ETF 详细动量数据（从数据库读最新一条）。"""
    rows = await execute_query("""
        SELECT * FROM momentum_history
        WHERE code = ?
        ORDER BY calc_time DESC
        LIMIT 1
    """, (code,))
    if not rows:
        raise HTTPException(status_code=404, detail="ETF 数据不存在或尚未更新")

    row = rows[0]
    short_m = row.get("short_momentum") or 0
    medium_m = row.get("medium_momentum") or 0
    return {
        "code": row["code"],
        "name": row.get("name", ""),
        "short_momentum": short_m,
        "medium_momentum": medium_m,
        "combined_score": row.get("combined_score"),
        "signal": row.get("signal"),
        "daily_change": row.get("daily_change", 0),
        "current_price": row.get("current_price", 0),
        "above_ma60": bool(row.get("above_ma60")),
        "update_date": (row.get("calc_time") or "")[:10],
        "calc_time": row.get("calc_time"),
    }