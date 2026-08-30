"""ETF 双动量轮动策略。"""

from typing import Any

import numpy as np
import pandas as pd

from app.services.backtest.base import BacktestStrategy


class EtfDualMomentumStrategy(BacktestStrategy):
    """ETF 双动量轮动策略。

    参数：
    - universe: 标的池代码列表
    - short_window: 短期动量窗口（默认 20）
    - ma_window: 均线窗口（默认 60）
    - factor_type: return（涨跌幅）或 sharpe（夏普比率）
    - use_ma_filter: 是否仅价格在 60 日线上方才参与排名
    - buy_threshold: 买入阈值（return 模式下默认 3%，sharpe 模式下默认 0）
    - top_n: 选前几名等权持有（默认 1）
    - rebalance_freq: daily / weekly / monthly

    规则：
    - 综合评分 = 短期动量（return 模式为 20 日涨跌幅，sharpe 模式为 20 日夏普）
    - 长期趋势过滤 = 当前价格是否大于 ma_window 日均线（默认 60 日线）
    - 双动量 = 相对动量（评分排名）+ 绝对动量（价格在均线上方）
    """

    strategy_type = "etf_dual_momentum"
    name = "ETF 双动量轮动"
    description = "基于短期动量排名 + 60日线趋势过滤，每日/周/月调仓，持有 top N 的 ETF 轮动策略"

    def params_schema(self) -> list[dict]:
        return [
            {
                "name": "universe",
                "type": "list",
                "label": "标的池",
                "default": ["159915", "512890", "159941", "518880"],
                "required": True,
                "description": "参与轮动的 ETF 代码列表",
            },
            {
                "name": "initial_capital",
                "type": "number",
                "label": "初始资金",
                "default": 10000,
                "min": 1000,
                "max": 100000000,
                "step": 1000,
            },
            {
                "name": "cash_rate",
                "type": "number",
                "label": "空仓年化收益",
                "default": 0.01,
                "min": 0,
                "max": 0.1,
                "step": 0.005,
                "precision": 3,
            },
            {
                "name": "start_date",
                "type": "date",
                "label": "开始日期",
                "default": "2021-07-05",
                "required": True,
            },
            {
                "name": "end_date",
                "type": "date",
                "label": "结束日期",
                "default": "2026-07-02",
                "required": True,
            },
            {
                "name": "benchmark_code",
                "type": "string",
                "label": "基准代码",
                "default": "510300",
                "required": True,
                "description": "用于对比的基准指数/ETF",
            },
            {
                "name": "short_window",
                "type": "number",
                "label": "短期窗口",
                "default": 20,
                "min": 1,
                "max": 252,
                "step": 1,
                "required": True,
            },
            {
                "name": "ma_window",
                "type": "number",
                "label": "均线窗口",
                "default": 60,
                "min": 1,
                "max": 500,
                "step": 1,
                "required": True,
                "description": "趋势过滤用的均线窗口，默认 60 日线",
            },
            {
                "name": "factor_type",
                "type": "select",
                "label": "因子类型",
                "default": "return",
                "options": [
                    {"value": "return", "label": "涨跌幅"},
                    {"value": "sharpe", "label": "夏普比率"},
                ],
                "required": True,
            },
            {
                "name": "use_ma_filter",
                "type": "boolean",
                "label": "启用均线过滤",
                "default": True,
                "required": True,
            },
            {
                "name": "buy_threshold",
                "type": "number",
                "label": "买入阈值",
                "default": 3.0,
                "min": -100,
                "max": 100,
                "step": 0.1,
                "description": "return 模式下默认 3（%），sharpe 模式下建议 0",
                "required": True,
            },
            {
                "name": "top_n",
                "type": "number",
                "label": "持仓数量",
                "default": 1,
                "min": 1,
                "max": 10,
                "step": 1,
                "required": True,
            },
            {
                "name": "rebalance_freq",
                "type": "select",
                "label": "调仓频率",
                "default": "weekly",
                "options": [
                    {"value": "daily", "label": "每日"},
                    {"value": "weekly", "label": "每周"},
                    {"value": "monthly", "label": "每月"},
                ],
                "required": True,
            },
            {
                "name": "rebalance_weekday",
                "type": "number",
                "label": "每周调仓日",
                "default": 4,
                "min": 0,
                "max": 6,
                "step": 1,
                "description": "0=周一，4=周五",
            },
            {
                "name": "rebalance_monthday",
                "type": "number",
                "label": "每月调仓日",
                "default": -1,
                "min": -1,
                "max": 31,
                "step": 1,
                "description": "-1 表示月末",
            },
            {
                "name": "risk_free_rate",
                "type": "number",
                "label": "无风险利率",
                "default": 0.02,
                "min": 0,
                "max": 0.1,
                "step": 0.001,
                "precision": 3,
                "description": "用于计算夏普比率，默认 2%",
            },
            {
                "name": "fee_rate",
                "type": "number",
                "label": "交易手续费",
                "default": 0.0001,
                "min": 0,
                "max": 0.01,
                "step": 0.0001,
                "precision": 4,
                "description": "万1 = 0.0001",
            },
        ]

    @staticmethod
    def _calc_return_momentum(prices: pd.Series, window: int) -> pd.Series:
        return (prices - prices.shift(window)) / prices.shift(window) * 100

    @staticmethod
    def _calc_sharpe(prices: pd.Series, window: int) -> pd.Series:
        daily_returns = prices.pct_change()
        return (
            daily_returns.rolling(window=window).mean()
            / daily_returns.rolling(window=window).std()
            * np.sqrt(252)
        )

    def prepare_data(self, prices_df: pd.DataFrame, params: dict[str, Any]) -> dict:
        codes = params.get("universe", list(prices_df.columns))
        short_window = int(params.get("short_window", 20))
        ma_window = int(params.get("ma_window", 60))
        factor_type = params.get("factor_type", "return")

        momentum = {}
        ma = {}
        for code in codes:
            if code not in prices_df.columns:
                continue
            prices = prices_df[code]
            if factor_type == "sharpe":
                momentum[f"{code}_short"] = self._calc_sharpe(prices, short_window)
            else:
                momentum[f"{code}_short"] = self._calc_return_momentum(prices, short_window)
            ma[code] = prices.rolling(window=ma_window).mean()

        return {
            "momentum": pd.DataFrame(momentum).reindex(prices_df.index),
            "ma": pd.DataFrame(ma).reindex(prices_df.index),
            "codes": codes,
            "factor_type": factor_type,
        }

    def on_rebalance_day(
        self,
        date: pd.Timestamp,
        prices_df: pd.DataFrame,
        prepared_data: dict,
        current_holdings: dict[str, float],
        params: dict[str, Any],
    ) -> dict[str, float]:
        factor_type = prepared_data["factor_type"]
        mom_df = prepared_data["momentum"]
        ma_df = prepared_data["ma"]
        codes = prepared_data["codes"]
        use_ma_filter = bool(params.get("use_ma_filter", True))
        buy_threshold = float(params.get("buy_threshold", 3.0))
        top_n = int(params.get("top_n", 1))

        scores = {}
        for code in codes:
            if code not in prices_df.columns:
                continue
            short_m = mom_df.loc[date, f"{code}_short"]
            if pd.isna(short_m):
                continue

            combined = short_m
            price = prices_df.loc[date, code]

            if use_ma_filter:
                ma = ma_df.loc[date, code]
                if pd.isna(ma) or price <= ma:
                    continue

            # 买入阈值
            if factor_type == "sharpe":
                if combined <= 0:
                    continue
            else:
                if combined <= buy_threshold:
                    continue

            scores[code] = combined

        if not scores:
            return {}

        selected = sorted(scores, key=scores.get, reverse=True)[:top_n]
        weight = 1.0 / len(selected)
        return {code: weight for code in selected}
