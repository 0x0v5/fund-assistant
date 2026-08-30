"""回测引擎。"""

from typing import Any

import pandas as pd

from app.services.backtest.base import BacktestStrategy


class BacktestEngine:
    """通用回测引擎。

    支持多标的、现金收益、再平衡、交易手续费、交易记录、每日净值记录。
    """

    def __init__(
        self,
        strategy: BacktestStrategy,
        prices_df: pd.DataFrame,
        benchmark_df: pd.Series,
        params: dict[str, Any],
    ):
        self.strategy = strategy
        self.prices_df = prices_df
        self.benchmark_df = benchmark_df
        self.params = params

        self.initial_capital = float(params.get("initial_capital", 10000.0))
        self.cash_rate = float(params.get("cash_rate", 0.01))
        self.fee_rate = float(params.get("fee_rate", 0.0001))
        self.daily_cash_factor = (1.0 + self.cash_rate) ** (1.0 / 252.0)

        self.cash = self.initial_capital
        self.shares: dict[str, float] = {}
        self.trades: list[dict] = []
        self.daily_records: list[dict] = []

    def _portfolio_value(self, date: pd.Timestamp) -> float:
        value = self.cash
        for code, shares in self.shares.items():
            if code in self.prices_df.columns and date in self.prices_df.index:
                price = self.prices_df.loc[date, code]
                if not pd.isna(price):
                    value += shares * price
        return value

    def _benchmark_value(self, date: pd.Timestamp, initial_value: float) -> float:
        if date not in self.benchmark_df.index:
            return initial_value
        bench_price = self.benchmark_df.loc[date]
        if pd.isna(bench_price):
            return initial_value
        # 以回测区间内第一个有效基准价格为起点
        valid_bench = self.benchmark_df.dropna()
        if valid_bench.empty:
            return initial_value
        first_price = valid_bench.iloc[0]
        if first_price == 0:
            return initial_value
        return initial_value * bench_price / first_price

    def _execute_rebalance(self, date: pd.Timestamp, target_weights: dict[str, float]):
        """执行调仓：先卖出不在目标中的持仓，再按目标权重买入，扣除手续费。"""
        total_value = self._portfolio_value(date)

        # 卖出当前持仓中不在目标中的部分
        current_codes = set(self.shares.keys())
        target_codes = set(target_weights.keys())
        sell_codes = current_codes - target_codes

        for code in list(sell_codes):
            price = self.prices_df.loc[date, code]
            if pd.isna(price):
                continue
            shares = self.shares.pop(code, 0.0)
            value = shares * price
            fee = value * self.fee_rate
            self.cash += value - fee
            self.trades.append({
                "date": date,
                "action": "sell",
                "code": code,
                "price": price,
                "shares": shares,
                "value": value,
                "fee": fee,
            })

        # 按目标权重买入（等权分配目标市值）
        for code, weight in target_weights.items():
            if code not in self.prices_df.columns:
                continue
            price = self.prices_df.loc[date, code]
            if pd.isna(price):
                continue
            target_value = total_value * weight
            current_value = self.shares.get(code, 0.0) * price
            diff_value = target_value - current_value

            if diff_value > 0:
                # 预留手续费后的实际可买金额
                max_invest_value = self.cash / (1.0 + self.fee_rate)
                invest_value = min(diff_value, max_invest_value)
                if invest_value <= 0:
                    continue
                shares_to_buy = invest_value / price
                cost = shares_to_buy * price
                fee = cost * self.fee_rate
                self.shares[code] = self.shares.get(code, 0.0) + shares_to_buy
                self.cash -= cost + fee
                self.trades.append({
                    "date": date,
                    "action": "buy",
                    "code": code,
                    "price": price,
                    "shares": shares_to_buy,
                    "value": cost,
                    "fee": fee,
                })
            elif diff_value < 0:
                shares_to_sell = abs(diff_value) / price
                current_shares = self.shares.get(code, 0.0)
                shares_to_sell = min(shares_to_sell, current_shares)
                if shares_to_sell > 0:
                    value = shares_to_sell * price
                    fee = value * self.fee_rate
                    self.shares[code] = current_shares - shares_to_sell
                    if abs(self.shares[code]) < 1e-12:
                        del self.shares[code]
                    self.cash += value - fee
                    self.trades.append({
                        "date": date,
                        "action": "sell",
                        "code": code,
                        "price": price,
                        "shares": shares_to_sell,
                        "value": value,
                        "fee": fee,
                    })

    def run(self) -> dict:
        """执行回测，返回运行结果。"""
        prepared_data = self.strategy.prepare_data(self.prices_df, self.params)

        dates = self.prices_df.index
        peak_value = self.initial_capital

        for i, date in enumerate(dates):
            # 从第二天开始，先对昨日剩余现金计息
            if i > 0:
                self.cash *= self.daily_cash_factor

            # 调用策略交易日逻辑（双动量会再平衡，定投会买入）
            current_holdings = {code: self.shares.get(code, 0.0) for code in self.prices_df.columns}
            self.strategy.on_trading_day(
                date, self.prices_df, prepared_data, current_holdings, self.params, self
            )

            portfolio_value = self._portfolio_value(date)
            benchmark_value = self._benchmark_value(date, self.initial_capital)
            drawdown = (portfolio_value - peak_value) / peak_value * 100 if peak_value > 0 else 0
            if portfolio_value > peak_value:
                peak_value = portfolio_value

            holding_codes = ",".join(self.shares.keys()) if self.shares else ""
            self.daily_records.append({
                "date": date,
                "portfolio_value": portfolio_value,
                "benchmark_value": benchmark_value,
                "holding_code": holding_codes,
                "cash": self.cash,
                "drawdown": drawdown,
            })

        final_date = dates[-1] if len(dates) else None
        final_prices = {}
        if final_date is not None:
            for code in self.shares.keys():
                if code in self.prices_df.columns:
                    price = self.prices_df.loc[final_date, code]
                    if not pd.isna(price):
                        final_prices[code] = float(price)

        return {
            "daily_records": self.daily_records,
            "trades": self.trades,
            "final_value": self.daily_records[-1]["portfolio_value"] if self.daily_records else self.initial_capital,
            "strategy_type": self.strategy.strategy_type,
            "final_prices": final_prices,
        }
