"""Pydantic models for API request/response."""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class QdiiFund(BaseModel):
    code: str
    name: str
    premium: float
    quota_status: str
    last_update: datetime


class QdiiQuotaResponse(BaseModel):
    funds: List[QdiiFund]
    update_time: datetime


class FundIndicator(BaseModel):
    name: str
    value: Optional[float] = None
    score: int = Field(le=100, ge=0)
    note: Optional[str] = None


class FundEval(BaseModel):
    code: str
    name: str
    score: int = Field(le=100, ge=0)
    indicators: List[FundIndicator]
    radar_data: dict
    info: dict = Field(default_factory=dict)


class FundHistory(BaseModel):
    code: str
    date: str
    nav: float
    accumulated_nav: float


class EtfSignal(BaseModel):
    code: str
    name: str
    short_momentum: float
    medium_momentum: float
    combined_score: float
    signal: str  # "buy", "hold", "sell"
    daily_change: float = 0  # 最新一天涨跌幅
    current_price: float = 0  # 当前价格
    above_ma60: bool = False  # 当前价格是否大于 60 日线
    update_date: Optional[str] = None  # 更新日期


class EtfMomentum(BaseModel):
    strategy: str
    signal: str
    holdings: List[EtfSignal]
    candidates: List[EtfSignal]
    last_update: datetime
    switch_suggestion: Optional[str] = None  # 切换建议


class IndustryFund(BaseModel):
    code: str
    name: str
    industry: str
    nav: float
    ytd_return: float
    risk_level: str


class IndustryFundsResponse(BaseModel):
    industries: List[dict]
    update_time: datetime


# ============ 回测相关 ============

class BacktestParamField(BaseModel):
    name: str
    type: str  # number, string, select, boolean, date, list
    label: str
    default: Optional[Any] = None
    required: bool = False
    options: Optional[List[dict]] = None  # for select
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    description: Optional[str] = None


class BacktestStrategyInfo(BaseModel):
    type: str
    name: str
    description: str
    params_schema: List[BacktestParamField]


class BacktestRunRequest(BaseModel):
    strategy_type: str
    name: Optional[str] = None
    params: dict


class BacktestRunSummary(BaseModel):
    id: int
    name: Optional[str]
    strategy_type: str
    start_date: str
    end_date: str
    initial_capital: float
    total_return: Optional[float]
    cagr: Optional[float]
    benchmark_total_return: Optional[float]
    alpha: Optional[float]
    max_drawdown: Optional[float]
    sharpe: Optional[float]
    annual_volatility: Optional[float]
    win_rate: Optional[float]
    profit_loss_ratio: Optional[float]
    total_trades: Optional[int]
    created_at: Optional[str]


class BacktestRunDetail(BaseModel):
    id: int
    name: Optional[str]
    strategy_type: str
    params: dict
    universe: List[str]
    benchmark_code: str
    start_date: str
    end_date: str
    initial_capital: float
    cash_rate: float
    total_return: Optional[float]
    cagr: Optional[float]
    benchmark_total_return: Optional[float]
    alpha: Optional[float]
    max_drawdown: Optional[float]
    sharpe: Optional[float]
    annual_volatility: Optional[float]
    max_consecutive_losing_days: Optional[int]
    total_rebalances: Optional[int]
    total_trades: Optional[int]
    win_rate: Optional[float]
    profit_loss_ratio: Optional[float]
    cash_position_days_ratio: Optional[float]
    created_at: Optional[str]


class BacktestDailyValue(BaseModel):
    date: str
    portfolio_value: float
    benchmark_value: float
    holding_code: Optional[str]
    cash: float
    drawdown: Optional[float]


class BacktestTrade(BaseModel):
    date: str
    action: str
    code: str
    price: float
    shares: float
    value: float


class BacktestCompareRequest(BaseModel):
    run_ids: List[int]


class BacktestCompareResponse(BaseModel):
    runs: List[BacktestRunDetail]
    dates: List[str]
    equity_series: dict  # run_id -> List[float]
    benchmark_series: dict  # run_id -> List[float]
