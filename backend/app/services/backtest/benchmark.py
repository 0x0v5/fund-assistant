"""基准数据服务。"""

import asyncio
from datetime import datetime

import pandas as pd

from app.db.database import execute_query, execute_update, execute_many
from app.services.crawler import fund_data


DEFAULT_BENCHMARK_CODE = "510300"  # 沪深300ETF


class BenchmarkService:
    """加载并缓存基准数据到 fund_nav。"""

    @staticmethod
    async def load_benchmark(
        code: str = DEFAULT_BENCHMARK_CODE,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.Series:
        """加载基准日K收盘价序列。

        优先从 fund_nav 读；缺失时调 crawler.get_etf_hist 抓取并写入 fund_nav。
        """
        # 1. 从 DB 读
        rows = await execute_query(
            "SELECT date, nav, accumulated_nav FROM fund_nav WHERE code = ? ORDER BY date ASC",
            (code,),
        )

        if rows:
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            # 优先用 accumulated_nav，缺失用 nav
            series = df["accumulated_nav"].fillna(df["nav"])

            # 如果日期范围覆盖，直接返回
            if start_date and end_date:
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                if series.index.min() <= start_dt and series.index.max() >= end_dt:
                    return series
        else:
            series = pd.Series(dtype=float)

        # 2. 从数据源抓取
        # 估算需要的天数
        if start_date and end_date:
            days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days + 365
        else:
            days = 1825  # 5 年
        hist_df = await asyncio.to_thread(fund_data.get_etf_hist, code, days=days)

        if hist_df is None or hist_df.empty:
            # 抓不到也返回 DB 里已有的
            return series

        hist_df["date"] = pd.to_datetime(hist_df["date"])
        hist_df = hist_df[hist_df["date"].dt.weekday < 5]
        hist_df = hist_df.sort_values("date")

        prices = pd.Series(hist_df["close"].values, index=hist_df["date"])
        adjusted = fund_data.adjust_for_splits(prices)

        # 3. 写入 fund_nav（nav=原始收盘价，accumulated_nav=后复权价）
        nav_records = [
            (code, date.strftime("%Y-%m-%d"), float(close), float(adjusted.loc[date]))
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

        return adjusted.sort_index()
