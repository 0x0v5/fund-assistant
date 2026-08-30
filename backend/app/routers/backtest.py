"""基金回测 API router."""

import json
from datetime import datetime
from typing import Optional
import asyncio

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.db.database import execute_query, execute_update, execute_many
from app.models.schemas import (
    BacktestCompareRequest,
    BacktestCompareResponse,
    BacktestDailyValue,
    BacktestRunDetail,
    BacktestRunRequest,
    BacktestRunSummary,
    BacktestStrategyInfo,
    BacktestTrade,
)
from app.services.backtest.benchmark import BenchmarkService, DEFAULT_BENCHMARK_CODE
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.metrics import BacktestMetricsCalculator
from app.services.backtest.registry import get_strategy, list_strategies
from app.services.crawler import fund_data

router = APIRouter()


async def _load_prices(universe: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """加载标的池历史净值，缺失时自动抓取并写入 fund_nav。"""
    all_data = []
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    for code in universe:
        rows = await execute_query(
            "SELECT date, accumulated_nav, nav FROM fund_nav WHERE code = ? ORDER BY date ASC",
            (code,),
        )

        if rows:
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = df["accumulated_nav"].fillna(df["nav"])
            # 检查是否覆盖区间
            if df["date"].min() > start_dt or df["date"].max() < end_dt:
                rows = []  # 触发重新抓取

        if not rows:
            days = (end_dt - start_dt).days + 365
            hist_df = await asyncio.to_thread(fund_data.get_etf_hist, code, days=days)
            if hist_df is None or hist_df.empty:
                continue
            hist_df["date"] = pd.to_datetime(hist_df["date"])
            hist_df = hist_df[hist_df["date"].dt.weekday < 5]
            hist_df = hist_df.sort_values("date")

            # 对收盘价做拆分调整，accumulated_nav 用后复权价
            prices = pd.Series(hist_df["close"].values, index=hist_df["date"])
            adjusted = fund_data.adjust_for_splits(prices)

            # 批量写入 fund_nav
            nav_records = [
                (
                    code,
                    date.strftime("%Y-%m-%d"),
                    float(close),
                    float(adjusted.loc[date]),
                )
                for date, close in prices.items()
            ]
            if nav_records:
                await execute_many(
                    """
                    INSERT INTO fund_nav (code, date, nav, accumulated_nav)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code, date) DO UPDATE SET
                        nav = excluded.nav,
                        accumulated_nav = excluded.accumulated_nav
                    """,
                    nav_records,
                )
            df = hist_df.rename(columns={"close": "value"})
            df["value"] = adjusted.values

        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
        for _, row in df.iterrows():
            all_data.append({
                "code": code,
                "date": row["date"],
                "value": float(row["value"]),
            })

    if not all_data:
        raise HTTPException(status_code=400, detail="无法获取任何标的的历史数据")

    df = pd.DataFrame(all_data)
    prices_df = df.pivot(index="date", columns="code", values="value").sort_index()
    return prices_df


def _fill_defaults(strategy, params: dict) -> dict:
    """用 schema 默认值补齐缺失参数。"""
    defaults = {field["name"]: field.get("default") for field in strategy.params_schema()}
    defaults.update(params)
    return defaults


@router.get("/strategies", response_model=list[BacktestStrategyInfo])
async def get_strategies():
    """列出支持的回测策略及参数 schema。"""
    return list_strategies()


@router.post("/run", response_model=BacktestRunDetail)
async def run_backtest(request: BacktestRunRequest):
    """运行回测并持久化结果。"""
    try:
        strategy = get_strategy(request.strategy_type)
        params = _fill_defaults(strategy, request.params)

        universe = params.get("universe")
        if not universe:
            raise HTTPException(status_code=400, detail="标的池 universe 不能为空")

        start_date = params.get("start_date")
        end_date = params.get("end_date")
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须指定 start_date 和 end_date")

        benchmark_code = params.get("benchmark_code", DEFAULT_BENCHMARK_CODE)
        initial_capital = float(params.get("initial_capital", 10000.0))
        cash_rate = float(params.get("cash_rate", 0.01))

        # 加载价格数据
        prices_df = await _load_prices(universe, start_date, end_date)
        if prices_df.empty:
            raise HTTPException(status_code=400, detail="加载价格数据失败")

        # 加载基准
        benchmark_series = await BenchmarkService.load_benchmark(benchmark_code, start_date, end_date)
        if benchmark_series.empty:
            raise HTTPException(status_code=400, detail=f"无法加载基准数据: {benchmark_code}")

        # 运行回测
        engine = BacktestEngine(strategy, prices_df, benchmark_series, params)
        result = engine.run()

        # 计算指标
        risk_free_rate = float(params.get("risk_free_rate", 0.02))
        metrics = BacktestMetricsCalculator(
            result["daily_records"], result["trades"], initial_capital,
            strategy_type=request.strategy_type, risk_free_rate=risk_free_rate,
            final_prices=result.get("final_prices", {}),
        ).calculate()

        # 写入数据库
        created_at = datetime.now().isoformat()
        run_id = await execute_update(
            """
            INSERT INTO backtest_runs
            (name, strategy_type, params, universe, benchmark_code, start_date, end_date,
             initial_capital, cash_rate, total_return, cagr, benchmark_total_return, alpha,
             max_drawdown, sharpe, annual_volatility, max_consecutive_losing_days,
             total_rebalances, total_trades, win_rate, profit_loss_ratio, cash_position_days_ratio, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.name or f"{strategy.name} {created_at[:19]}",
                request.strategy_type,
                json.dumps(params, ensure_ascii=False, default=str),
                json.dumps(universe, ensure_ascii=False),
                benchmark_code,
                start_date,
                end_date,
                initial_capital,
                cash_rate,
                metrics["total_return"],
                metrics["cagr"],
                metrics["benchmark_total_return"],
                metrics["alpha"],
                metrics["max_drawdown"],
                metrics["sharpe"],
                metrics["annual_volatility"],
                metrics["max_consecutive_losing_days"],
                metrics["total_rebalances"],
                metrics["total_trades"],
                metrics["win_rate"],
                metrics["profit_loss_ratio"],
                metrics["cash_position_days_ratio"],
                created_at,
            ),
        )
        # execute_update 对 INSERT 返回 cursor.lastrowid，即新 run_id

        # 写入每日净值
        daily_records = [
            (
                run_id,
                record["date"].strftime("%Y-%m-%d"),
                record["portfolio_value"],
                record["benchmark_value"],
                record["holding_code"],
                record["cash"],
                record["drawdown"],
            )
            for record in result["daily_records"]
        ]
        if daily_records:
            await execute_many(
                """
                INSERT INTO backtest_daily_values
                (run_id, date, portfolio_value, benchmark_value, holding_code, cash, drawdown)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                daily_records,
            )

        # 写入交易明细
        trades = [
            (
                run_id,
                trade["date"].strftime("%Y-%m-%d"),
                trade["action"],
                trade["code"],
                trade["price"],
                trade["shares"],
                trade["value"],
            )
            for trade in result["trades"]
        ]
        if trades:
            await execute_many(
                """
                INSERT INTO backtest_trades
                (run_id, date, action, code, price, shares, value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                trades,
            )

        # 组装返回
        detail = {
            "id": run_id,
            "name": request.name or f"{strategy.name} {created_at[:19]}",
            "strategy_type": request.strategy_type,
            "params": params,
            "universe": universe,
            "benchmark_code": benchmark_code,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "cash_rate": cash_rate,
            **metrics,
            "created_at": created_at,
        }
        return detail

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {str(e)}")


@router.get("/runs", response_model=list[BacktestRunSummary])
async def list_runs(strategy_type: Optional[str] = None, limit: int = 50):
    """列出历史回测。"""
    if strategy_type:
        rows = await execute_query(
            """
            SELECT id, name, strategy_type, start_date, end_date, initial_capital,
                   total_return, cagr, benchmark_total_return, alpha, max_drawdown,
                   sharpe, annual_volatility, win_rate, profit_loss_ratio, total_trades, created_at
            FROM backtest_runs
            WHERE strategy_type = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (strategy_type, limit),
        )
    else:
        rows = await execute_query(
            """
            SELECT id, name, strategy_type, start_date, end_date, initial_capital,
                   total_return, cagr, benchmark_total_return, alpha, max_drawdown,
                   sharpe, annual_volatility, win_rate, profit_loss_ratio, total_trades, created_at
            FROM backtest_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    return rows


@router.get("/runs/{run_id}", response_model=BacktestRunDetail)
async def get_run(run_id: int):
    """获取单条回测详情。"""
    rows = await execute_query(
        """
        SELECT * FROM backtest_runs WHERE id = ?
        """,
        (run_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="回测记录不存在")

    row = rows[0]
    detail = {
        "id": row["id"],
        "name": row["name"],
        "strategy_type": row["strategy_type"],
        "params": json.loads(row["params"]),
        "universe": json.loads(row["universe"]),
        "benchmark_code": row["benchmark_code"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "initial_capital": row["initial_capital"],
        "cash_rate": row["cash_rate"],
        "total_return": row["total_return"],
        "cagr": row["cagr"],
        "benchmark_total_return": row["benchmark_total_return"],
        "alpha": row["alpha"],
        "max_drawdown": row["max_drawdown"],
        "sharpe": row["sharpe"],
        "annual_volatility": row["annual_volatility"],
        "max_consecutive_losing_days": row["max_consecutive_losing_days"],
        "total_rebalances": row["total_rebalances"],
        "total_trades": row["total_trades"],
        "win_rate": row["win_rate"],
        "profit_loss_ratio": row["profit_loss_ratio"],
        "cash_position_days_ratio": row["cash_position_days_ratio"],
        "created_at": row["created_at"],
    }
    return detail


@router.get("/runs/{run_id}/equity", response_model=list[BacktestDailyValue])
async def get_equity(run_id: int):
    """获取回测每日净值序列。"""
    rows = await execute_query(
        """
        SELECT date, portfolio_value, benchmark_value, holding_code, cash, drawdown
        FROM backtest_daily_values
        WHERE run_id = ?
        ORDER BY date ASC
        """,
        (run_id,),
    )
    return rows


@router.get("/runs/{run_id}/trades", response_model=list[BacktestTrade])
async def get_trades(run_id: int):
    """获取回测交易明细。"""
    rows = await execute_query(
        """
        SELECT date, action, code, price, shares, value
        FROM backtest_trades
        WHERE run_id = ?
        ORDER BY date ASC, id ASC
        """,
        (run_id,),
    )
    return rows


@router.post("/compare", response_model=BacktestCompareResponse)
async def compare_runs(request: BacktestCompareRequest):
    """对比多个回测结果。"""
    if len(request.run_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要选择 2 个回测进行对比")

    runs = []
    for run_id in request.run_ids:
        detail = await get_run(run_id)
        runs.append(detail)

    # 对齐日期：取所有 run 的日期交集
    all_dates_sets = []
    equity_series = {}
    benchmark_series = {}

    for run in runs:
        rows = await execute_query(
            "SELECT date, portfolio_value, benchmark_value FROM backtest_daily_values WHERE run_id = ? ORDER BY date ASC",
            (run["id"],),
        )
        dates = [r["date"] for r in rows]
        all_dates_sets.append(set(dates))
        equity_series[str(run["id"])] = {r["date"]: r["portfolio_value"] for r in rows}
        benchmark_series[str(run["id"])] = {r["date"]: r["benchmark_value"] for r in rows}

    common_dates = sorted(set.intersection(*all_dates_sets) if all_dates_sets else [])

    aligned_equity = {}
    aligned_benchmark = {}
    for run in runs:
        rid = str(run["id"])
        aligned_equity[rid] = [equity_series[rid].get(d) for d in common_dates]
        aligned_benchmark[rid] = [benchmark_series[rid].get(d) for d in common_dates]

    return {
        "runs": runs,
        "dates": common_dates,
        "equity_series": aligned_equity,
        "benchmark_series": aligned_benchmark,
    }


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int):
    """删除回测及其子表数据。"""
    await execute_update("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
    await execute_update("DELETE FROM backtest_daily_values WHERE run_id = ?", (run_id,))
    await execute_update("DELETE FROM backtest_runs WHERE id = ?", (run_id,))
    return {"message": "删除成功", "run_id": run_id}
