"""定投策略。"""

from typing import Any

import pandas as pd

from app.services.backtest.base import BacktestStrategy


class FixedInvestmentStrategy(BacktestStrategy):
    """定期定额投资策略。

    参数：
    - universe: 标的池，取第一个作为定投目标
    - fixed_amount: 每次定投金额
    - frequency: 定投频率（weekly / monthly）
    - rebalance_weekday: 每周定投日（0=周一，4=周五）
    - rebalance_monthday: 每月定投日（-1=月末）
    - start_date / end_date: 回测区间
    - initial_capital: 初始现金，默认为 0
    - cash_rate: 空仓年化收益
    """

    strategy_type = "fixed_investment"
    name = "定投策略"
    description = "定期定额投资单只基金/ETF，按周或月投入固定金额"

    def params_schema(self) -> list[dict]:
        return [
            {
                "name": "universe",
                "type": "list",
                "label": "定投标的",
                "default": ["510300"],
                "required": True,
                "description": "定投的基金/ETF 代码，取第一个",
            },
            {
                "name": "fixed_amount",
                "type": "number",
                "label": "每次定投金额",
                "default": 1000,
                "min": 1,
                "max": 1000000,
                "step": 100,
                "required": True,
            },
            {
                "name": "rebalance_freq",
                "type": "select",
                "label": "定投频率",
                "default": "monthly",
                "options": [
                    {"value": "daily", "label": "每天"},
                    {"value": "weekly", "label": "每周"},
                    {"value": "biweekly", "label": "每双周"},
                    {"value": "monthly", "label": "每月"},
                ],
                "required": True,
            },
            {
                "name": "rebalance_weekday",
                "type": "number",
                "label": "每周定投日",
                "default": 4,
                "min": 0,
                "max": 6,
                "step": 1,
                "description": "0=周一，4=周五",
            },
            {
                "name": "rebalance_monthday",
                "type": "number",
                "label": "每月定投日",
                "default": 1,
                "min": -1,
                "max": 31,
                "step": 1,
                "description": "-1 表示月末",
            },
            {
                "name": "initial_capital",
                "type": "number",
                "label": "初始现金",
                "default": 0,
                "min": 0,
                "max": 10000000,
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
            {
                "name": "benchmark_code",
                "type": "string",
                "label": "基准代码",
                "default": "510300",
                "required": True,
                "description": "用于对比的基准指数/ETF",
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
        ]

    def prepare_data(self, prices_df: pd.DataFrame, params: dict[str, Any]) -> Any:
        return {}

    def on_rebalance_day(
        self,
        date: pd.Timestamp,
        prices_df: pd.DataFrame,
        prepared_data: Any,
        current_holdings: dict[str, float],
        params: dict[str, Any],
    ) -> dict[str, float]:
        """定投策略不使用权重再平衡，返回空。"""
        return {}

    def on_trading_day(
        self,
        date: pd.Timestamp,
        prices_df: pd.DataFrame,
        prepared_data: Any,
        current_holdings: dict[str, float],
        params: dict[str, Any],
        engine: Any,
    ):
        """在定投日用现金买入标的。"""
        if not self.is_rebalance_day(date, params):
            return

        universe = params.get("universe", [])
        if not universe:
            return
        code = universe[0]
        if code not in prices_df.columns:
            return

        price = prices_df.loc[date, code]
        if pd.isna(price) or price <= 0:
            return

        fixed_amount = float(params.get("fixed_amount", 0))
        if fixed_amount <= 0:
            return

        # 定投视为每期新增资金投入；手续费从当期中扣除，剩余金额买份额
        # （与再平衡引擎保持一致：fee 从 invest_value 中扣减）
        invest_amount = fixed_amount / (1 + engine.fee_rate)
        fee = fixed_amount - invest_amount
        shares = invest_amount / price
        engine.shares[code] = engine.shares.get(code, 0.0) + shares
        engine.trades.append({
            "date": date,
            "action": "buy",
            "code": code,
            "price": price,
            "shares": shares,
            "value": invest_amount,
            "fee": fee,
        })
