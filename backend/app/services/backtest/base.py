"""回测策略抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BacktestStrategy(ABC):
    """策略插件接口。

    每个具体策略需要实现：
    - strategy_type, name, description: 类属性
    - params_schema(): 返回参数定义列表，供前端动态渲染表单
    - prepare_data(prices_df, params): 预计算因子
    - on_rebalance_day(date, prices_df, prepared_data, current_holdings, params):
        返回目标持仓 dict: {code: weight}，空仓返回 {} 或 {"CASH": 1.0}
    """

    strategy_type: str = ""
    name: str = ""
    description: str = ""

    @abstractmethod
    def params_schema(self) -> list[dict]:
        """返回参数 schema 列表，元素格式与 BacktestParamField 对应。"""
        pass

    @abstractmethod
    def prepare_data(self, prices_df: pd.DataFrame, params: dict[str, Any]) -> Any:
        """在回测开始前预计算所需数据（动量、均线等）。"""
        pass

    @abstractmethod
    def on_rebalance_day(
        self,
        date: pd.Timestamp,
        prices_df: pd.DataFrame,
        prepared_data: Any,
        current_holdings: dict[str, float],
        params: dict[str, Any],
    ) -> dict[str, float]:
        """在调仓日返回目标持仓权重。

        返回 dict: {code: target_weight}，权重之和应等于 1.0（不含现金）。
        空仓返回 {}，引擎会自动持有现金。
        """
        pass

    def on_trading_day(
        self,
        date: pd.Timestamp,
        prices_df: pd.DataFrame,
        prepared_data: Any,
        current_holdings: dict[str, float],
        params: dict[str, Any],
        engine: Any,
    ):
        """每个交易日调用。默认仅在调仓日执行 on_rebalance_day + 再平衡。

        定投等非再平衡策略可重载此方法直接操作 engine。
        """
        if self.is_rebalance_day(date, params):
            target_weights = self.on_rebalance_day(
                date, prices_df, prepared_data, current_holdings, params
            )
            engine._execute_rebalance(date, target_weights)

    def is_rebalance_day(
        self,
        date: pd.Timestamp,
        params: dict[str, Any],
    ) -> bool:
        """判断某日是否为调仓日。默认支持 daily/weekly/biweekly/monthly。"""
        freq = params.get("rebalance_freq", "daily")
        if freq == "daily":
            return True
        if freq == "weekly":
            weekday = params.get("rebalance_weekday", 4)  # 默认周五
            return date.weekday() == weekday
        if freq == "biweekly":
            # 每双周一次，固定在 rebalance_weekday。
            # 用「距 Unix epoch 周一的整周数」奇偶判定——跨年也稳定。
            weekday = params.get("rebalance_weekday", 4)
            if date.weekday() != weekday:
                return False
            weeks_since_epoch = (date - pd.Timestamp("1970-01-05")).days // 7
            return weeks_since_epoch % 2 == 0
        if freq == "monthly":
            day = params.get("rebalance_monthday", -1)  # 默认月末
            if day == -1:
                return date.is_month_end
            return date.day == day
        return True
