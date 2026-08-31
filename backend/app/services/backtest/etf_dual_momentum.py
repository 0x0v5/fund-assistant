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
                "name": "consecutive_rank1_days",
                "type": "number",
                "label": "连续第一名天数门槛",
                "default": 3,
                "min": 1,
                "max": 30,
                "step": 1,
                "required": True,
                "description": "ETF 需连续 N 天排名第一才买入；=1 退化为旧行为（只看当天排名）",
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
        consec_n = int(params.get("consecutive_rank1_days", 3))

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

        # 预先计算「连续第一名天数」矩阵：date × code，仅在 use_ma_filter + buy_threshold
        # 双过滤后的有效 ETF 中按 combined_score 排；并列最高分都算 rank=1。
        # 非 rank=1 的位置写 0，表示当日不满足「连续 N 天第一」前置条件。
        scores_df = pd.DataFrame(momentum).reindex(prices_df.index)
        use_ma_filter = bool(params.get("use_ma_filter", True))
        buy_threshold = float(params.get("buy_threshold", 3.0))

        # valid 矩阵：date × code 布尔
        valid_mask = pd.DataFrame(True, index=scores_df.index, columns=codes)
        if use_ma_filter:
            ma_df = pd.DataFrame(ma).reindex(prices_df.index)
            for code in codes:
                if code not in ma_df.columns:
                    valid_mask[code] = False
                    continue
                valid_mask[code] = (
                    scores_df[f"{code}_short"].notna()
                    & ma_df[code].notna()
                    & (prices_df[code] > ma_df[code])
                )
        else:
            for code in codes:
                valid_mask[code] = scores_df[f"{code}_short"].notna()

        if factor_type == "sharpe":
            for code in codes:
                valid_mask[code] = valid_mask[code] & (scores_df[f"{code}_short"] > 0)
        else:
            for code in codes:
                valid_mask[code] = valid_mask[code] & (scores_df[f"{code}_short"] > buy_threshold)

        # rank_df：date × code，valid=True 中按 combined_score 降序排；并列最高分均置 1
        rank_df = pd.DataFrame(0, index=scores_df.index, columns=codes, dtype=float)
        for date in scores_df.index:
            row_scores = {}
            for code in codes:
                if valid_mask.loc[date, code]:
                    row_scores[code] = scores_df.loc[date, f"{code}_short"]
            if not row_scores:
                continue
            max_score = max(row_scores.values())
            for code, s in row_scores.items():
                if s == max_score:
                    rank_df.loc[date, code] = 1

        # consec_df：date × code，连续 rank=1 的天数；非 rank=1 置 0
        consec_df = pd.DataFrame(0, index=scores_df.index, columns=codes, dtype=int)
        for code in codes:
            is_rank1 = (rank_df[code] == 1).fillna(False)
            # 用 (non-rank1) cumsum 切段，每段内 cumcount = 连续 rank1 天数
            consec_df[code] = is_rank1.groupby((~is_rank1).cumsum()).cumcount()

        return {
            "momentum": scores_df,
            "ma": pd.DataFrame(ma).reindex(prices_df.index),
            "codes": codes,
            "factor_type": factor_type,
            "consec_df": consec_df,
            "consec_n": consec_n,
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
        consec_df = prepared_data.get("consec_df")
        consec_n = int(prepared_data.get("consec_n", params.get("consecutive_rank1_days", 3)))
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

            # 连续第一名门槛：precomputed consec_df 算的是 rank=1 连续天数
            # 这里要求「≥ consec_n 才买入」，避免单日第一名噪声
            if consec_n > 1 and consec_df is not None and date in consec_df.index:
                days = consec_df.loc[date, code]
                if pd.isna(days) or int(days) < consec_n:
                    continue

            scores[code] = combined

        if not scores:
            return {}

        selected = sorted(scores, key=scores.get, reverse=True)[:top_n]
        weight = 1.0 / len(selected)
        return {code: weight for code in selected}
