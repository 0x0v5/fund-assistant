"""策略注册表。"""

from app.services.backtest.base import BacktestStrategy
from app.services.backtest.etf_dual_momentum import EtfDualMomentumStrategy
from app.services.backtest.fixed_investment import FixedInvestmentStrategy


STRATEGIES: dict[str, type[BacktestStrategy]] = {
    EtfDualMomentumStrategy.strategy_type: EtfDualMomentumStrategy,
    FixedInvestmentStrategy.strategy_type: FixedInvestmentStrategy,
}


def get_strategy(strategy_type: str) -> BacktestStrategy:
    """根据类型返回策略实例。"""
    if strategy_type not in STRATEGIES:
        raise ValueError(f"未知策略类型: {strategy_type}，可用: {list(STRATEGIES.keys())}")
    return STRATEGIES[strategy_type]()


def list_strategies() -> list[dict]:
    """列出所有策略及其参数 schema。"""
    result = []
    for strategy_type, cls in STRATEGIES.items():
        inst = cls()
        result.append({
            "type": strategy_type,
            "name": inst.name,
            "description": inst.description,
            "params_schema": inst.params_schema(),
        })
    return result
