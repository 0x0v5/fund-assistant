"""回测指标计算。"""

import numpy as np
import pandas as pd


class BacktestMetricsCalculator:
    """根据回测结果计算各类指标。"""

    def __init__(
        self,
        daily_records: list[dict],
        trades: list[dict],
        initial_capital: float,
        strategy_type: str = "",
        risk_free_rate: float = 0.02,
        final_prices: dict[str, float] | None = None,
    ):
        self.daily_records = daily_records
        self.trades = trades
        self.initial_capital = initial_capital
        self.strategy_type = strategy_type
        self.risk_free_rate = risk_free_rate
        self.final_prices = final_prices or {}

        # 成本基准：双动量等再平衡策略用初始资金；定投策略需累加每次投入本金及手续费
        if strategy_type == "fixed_investment":
            self.total_invested = initial_capital + sum(
                (t["value"] + t.get("fee", 0.0)) for t in trades if t["action"] == "buy"
            )
        else:
            self.total_invested = initial_capital

        self.pv_df = pd.DataFrame(daily_records).set_index("date") if daily_records else pd.DataFrame()

    def calculate(self) -> dict:
        if self.pv_df.empty:
            return self._empty_metrics()

        # 过滤掉尚未开始投资的日期（portfolio_value <= 0）
        valid_pv = self.pv_df[self.pv_df["portfolio_value"] > 0]["portfolio_value"]
        if valid_pv.empty:
            return self._empty_metrics()

        final_value = valid_pv.iloc[-1]
        start_date = valid_pv.index[0]
        end_date = valid_pv.index[-1]
        days = (end_date - start_date).days
        years = days / 365.25 if days > 0 else 0

        # 累计收益 & 年化收益：
        # - 再平衡策略（双动量等）：资金一次性投入，用 (终值-本金)/本金
        # - 定投策略：资金分期投入，用 Modified Dietz (考虑资金时间价值)
        if self.strategy_type == "fixed_investment":
            total_return, cagr = self._dca_modified_dietz(
                valid_pv, start_date, end_date, days, years
            )
        else:
            cost_basis = self.total_invested if self.total_invested > 0 else self.initial_capital
            if cost_basis <= 0:
                cost_basis = 1.0  # 防止除零
            total_return = (final_value - cost_basis) / cost_basis * 100
            cagr = (
                ((final_value / cost_basis) ** (1 / years) - 1) * 100
                if years > 0 else 0
            )

        # 基准收益：基于有效区间第一天到最后一天
        benchmark_series = self.pv_df.loc[valid_pv.index, "benchmark_value"]
        final_benchmark = benchmark_series.iloc[-1]
        first_benchmark = benchmark_series.iloc[0]
        benchmark_total_return = (
            (final_benchmark - first_benchmark) / first_benchmark * 100
            if first_benchmark and first_benchmark > 0 else 0
        )
        alpha = total_return - benchmark_total_return

        # 最大回撤
        peak = valid_pv.cummax()
        drawdown = (valid_pv - peak) / peak * 100
        max_drawdown = drawdown.min()

        # 年化波动率 & 夏普（使用可配置无风险利率）
        daily_returns = valid_pv.pct_change().dropna()
        annual_volatility = daily_returns.std() * np.sqrt(252) * 100
        sharpe = (
            (cagr - self.risk_free_rate * 100) / annual_volatility
            if annual_volatility > 0 else 0
        )

        # 最大连续亏损天数
        max_consecutive_losing_days = self._max_consecutive_losing_days(valid_pv)

        # 调仓/交易次数
        total_rebalances = len([t for t in self.trades if t["action"] == "buy"])
        total_trades = len(self.trades)

        # 胜率 & 盈亏比
        win_rate, profit_loss_ratio = self._calc_win_rate_and_pl_ratio(final_value)

        # 空仓天数占比
        total_days = len(self.pv_df)
        cash_days = (self.pv_df["holding_code"] == "").sum()
        cash_position_days_ratio = cash_days / total_days * 100 if total_days > 0 else 0

        return {
            "total_return": round(total_return, 2),
            "cagr": round(cagr, 2),
            "benchmark_total_return": round(benchmark_total_return, 2),
            "alpha": round(alpha, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
            "annual_volatility": round(annual_volatility, 2),
            "max_consecutive_losing_days": int(max_consecutive_losing_days),
            "total_rebalances": int(total_rebalances),
            "total_trades": int(total_trades),
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "cash_position_days_ratio": round(cash_position_days_ratio, 2),
        }

    def _empty_metrics(self) -> dict:
        return {
            "total_return": 0,
            "cagr": 0,
            "benchmark_total_return": 0,
            "alpha": 0,
            "max_drawdown": 0,
            "sharpe": 0,
            "annual_volatility": 0,
            "max_consecutive_losing_days": 0,
            "total_rebalances": 0,
            "total_trades": 0,
            "win_rate": 0,
            "profit_loss_ratio": 0,
            "cash_position_days_ratio": 0,
        }

    def _dca_modified_dietz(
        self,
        valid_pv: "pd.Series",
        start_date: "pd.Timestamp",
        end_date: "pd.Timestamp",
        days: int,
        years: float,
    ) -> tuple[float, float]:
        """定投策略专用的 Modified Dietz 真实收益率（考虑资金时间价值）。

        公式（CFA / Morningstar 标准）：
            R = (EMV - BMV - Σ F_i) / (BMV + Σ w_i × F_i)

        其中：
            BMV = Beginning Market Value，期初市值
            EMV = Ending Market Value，期末市值
            F_i = 第 i 次外部净现金流（投入为正，提取为负）
            w_i = (T - t_i) / T，第 i 次现金流距期初的时间占比
            T   = 总回测天数

        对定投场景的约定：
            BMV = 期初市值（如果回测初始投资前的账面市值）。
                  这里我们以「首笔投入当天」作为分界——
                  首笔投入之前 BMV = 0（空仓），首笔投入当日及之后
                  BMV = 第一笔投入金额（投入即买入，账面立刻 = F_0）。
                  用「首笔买入总投入」作为期初，再加权。

        注意：若 initial_capital > 0，则首笔投入就是 BMV；否则 BMV=0。
        简化策略：BMV 取 self.initial_capital（用户设定的初始资金）。
        """
        if days <= 0 or years <= 0 or valid_pv.empty:
            return 0.0, 0.0

        v_end = float(valid_pv.iloc[-1])
        # BMV：用户设定的初始资金（定投页面默认 0）
        v_start = float(self.initial_capital) if self.initial_capital > 0 else 0.0

        # 构造现金流：F_i 约定投入为正
        flows = []
        for t in self.trades:
            if t["action"] == "buy":
                flows.append((pd.Timestamp(t["date"]), float(t["value"]) + float(t.get("fee", 0.0))))
            elif t["action"] == "sell":
                flows.append((pd.Timestamp(t["date"]), -float(t["value"])))

        if not flows:
            return 0.0, 0.0

        total_days = days
        net_flow = sum(amt for _, amt in flows)
        weighted = 0.0
        for dt, amt in flows:
            t_i_days = (dt - start_date).days
            if t_i_days < 0:
                w = 0.0
            elif t_i_days > total_days:
                w = 1.0
            else:
                w = (total_days - t_i_days) / total_days
            weighted += amt * w

        denominator = v_start + weighted
        if denominator <= 0:
            return 0.0, 0.0

        r_md = (v_end - v_start - net_flow) / denominator
        total_return = r_md * 100
        cagr = ((1 + r_md) ** (1 / years) - 1) * 100 if r_md > -1 else 0.0
        return total_return, cagr

    def _max_consecutive_losing_days(self, values: pd.Series) -> int:
        if values.empty:
            return 0
        changes = values.diff().dropna()
        max_streak = 0
        current_streak = 0
        for change in changes:
            if change < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    def _calc_win_rate_and_pl_ratio(self, final_value: float) -> tuple[float, float]:
        """计算胜率和盈亏比。

        每次买入视为一轮交易，找到后续同代码的卖出（或期末市值）作为平仓价。
        """
        profits = []
        losses = []

        for i, buy_trade in enumerate(self.trades):
            if buy_trade["action"] != "buy":
                continue
            code = buy_trade["code"]
            buy_price = buy_trade["price"]
            shares = buy_trade["shares"]

            # 找同代码的后续卖出
            sell_price = None
            for sell_trade in self.trades[i + 1:]:
                if sell_trade["action"] == "sell" and sell_trade["code"] == code:
                    sell_price = sell_trade["price"]
                    break

            # 未找到卖出，用期末该标的价格
            if sell_price is None:
                sell_price = self.final_prices.get(code)
                if sell_price is None:
                    continue

            pnl = (sell_price - buy_price) * shares
            if pnl > 0:
                profits.append(pnl)
            elif pnl < 0:
                losses.append(abs(pnl))

        total_rounds = len(profits) + len(losses)
        if total_rounds == 0:
            return 0.0, 0.0

        win_rate = len(profits) / total_rounds * 100
        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0

        return win_rate, profit_loss_ratio
