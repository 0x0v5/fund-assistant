"""基金评测计算服务"""

from __future__ import annotations  # 类型注解懒求值，pandas 可懒加载

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import statistics


class FundEvalService:
    """基金评测计算服务"""

    def __init__(self):
        pass

    @staticmethod
    def calc_score(indicators: Dict[str, float]) -> int:
        """计算综合评分 (0-100)。

        权重：
          - 1y/3y/5y 收益: 合计 30 分
          - 夏普比率: 15 分
          - Sortino 比率: 10 分
          - 卡玛比率: 10 分
          - 最大回撤 (反向): 15 分
          - 盈利概率: 5 分
          - 同类百分位（如果有）: 15 分
        """
        score = 50  # 基础分

        # 收益率权重 (合计 ±30)
        if "return_1y" in indicators and indicators["return_1y"] is not None:
            score += min(15, max(-15, indicators["return_1y"] * 0.5))
        if "return_3y" in indicators and indicators["return_3y"] is not None:
            score += min(15, max(-15, indicators["return_3y"] * 0.2))

        # 夏普比率 (±15)
        if "sharpe" in indicators and indicators["sharpe"] is not None:
            score += min(15, max(-15, indicators["sharpe"] * 5))

        # Sortino 比率 (±10)
        if "sortino" in indicators and indicators["sortino"] is not None:
            score += min(10, max(-10, indicators["sortino"] * 3))

        # 卡玛比率 (±10)
        if "calmar" in indicators and indicators["calmar"] is not None:
            score += min(10, max(-10, indicators["calmar"] * 3))

        # 最大回撤 (±15，回撤越大扣分越多)
        if "max_drawdown" in indicators and indicators["max_drawdown"] is not None:
            score += min(15, max(-15, -indicators["max_drawdown"] * 0.3))

        # 盈利概率 (±5)
        if "profit_prob" in indicators and indicators["profit_prob"] is not None:
            score += min(5, max(-5, (indicators["profit_prob"] - 50) * 0.1))

        # 同类百分位排名（0-100，转 ±15 分）
        if "return_1y_pct" in indicators and indicators["return_1y_pct"] is not None:
            score += (indicators["return_1y_pct"] - 50) * 0.3

        return max(0, min(100, int(score)))

    @staticmethod
    def calc_sharpe(returns: List[float], rf_rate: float = 0.03) -> float:
        """计算夏普比率."""
        if len(returns) < 2:
            return 0.0

        excess_returns = [r - rf_rate / 252 for r in returns]
        mean_excess = statistics.mean(excess_returns)
        std_excess = statistics.stdev(excess_returns) if len(excess_returns) > 1 else 0

        if std_excess == 0:
            return 0.0

        return round(mean_excess / std_excess * (252 ** 0.5), 2)

    @staticmethod
    def calc_max_drawdown(prices: List[float]) -> float:
        """计算最大回撤."""
        if len(prices) < 2:
            return 0.0

        peak = prices[0]
        max_dd = 0.0

        for price in prices:
            if price > peak:
                peak = price
            if peak > 0:
                dd = (peak - price) / peak
                if dd > max_dd:
                    max_dd = dd

        return round(max_dd * 100, 2)

    @staticmethod
    def calc_volatility(returns: List[float]) -> float:
        """计算波动率."""
        if len(returns) < 2:
            return 0.0

        return round(statistics.stdev(returns) * (252 ** 0.5) * 100, 2)

    @staticmethod
    def calc_sortino(returns: List[float], rf_rate: float = 0.03) -> float:
        """计算 Sortino 比率（只用下行波动）。"""
        if len(returns) < 2:
            return 0.0
        excess_returns = [r - rf_rate / 252 for r in returns]
        mean_excess = statistics.mean(excess_returns)
        downside = [r for r in returns if r < rf_rate / 252]
        if not downside:
            return 0.0
        down_dev = (sum((rf_rate / 252 - r) ** 2 for r in downside) / len(downside)) ** 0.5
        if down_dev == 0:
            return 0.0
        return round(mean_excess / down_dev * (252 ** 0.5), 2)

    @staticmethod
    def calc_calmar(returns_pct: float, max_drawdown: float) -> float:
        """计算卡玛比率（年化收益 / 最大回撤）。

        Args:
            returns_pct: 近 1 年收益率（百分比数字，如 12.5）
            max_drawdown: 最大回撤（百分比数字，如 15.2）
        """
        if not max_drawdown or max_drawdown <= 0:
            return 0.0
        return round(returns_pct / max_drawdown, 2)

    @staticmethod
    def calc_percentile_rank(value: float, peers: List[float]) -> float:
        """计算百分位排名（0-100，越大越好）。

        Args:
            value: 本基金某项指标值
            peers: 同类基金同一指标的所有值
        """
        if peers is None or len(peers) == 0:
            return 50.0
        below = sum(1 for p in peers if p < value)
        return round(below / len(peers) * 100, 1)

    @staticmethod
    def calc_profit_probability(returns: List[float]) -> float:
        """计算盈利概率（正收益天数占比）."""
        if not returns:
            return 0.0

        positive_days = sum(1 for r in returns if r > 0)
        return round(positive_days / len(returns) * 100, 2)

    @staticmethod
    def evaluate_radar_data(indicators: Dict[str, float]) -> Dict:
        """生成雷达图数据（5 维独立）。"""
        return_1y = indicators.get("return_1y") or 0
        max_dd = abs(indicators.get("max_drawdown") or 0)
        sharpe = indicators.get("sharpe") or 0
        profit_prob = indicators.get("profit_prob") or 50
        volatility = indicators.get("volatility") or 20

        radar_indicators = [
            {"name": "收益能力", "value": min(100, max(0, 50 + return_1y))},
            {"name": "稳定性", "value": min(100, max(0, 100 - max_dd))},
            {"name": "风险收益", "value": min(100, max(0, sharpe * 30 + 50))},
            {"name": "盈利概率", "value": min(100, max(0, profit_prob))},
            {"name": "低波动", "value": min(100, max(0, 100 - volatility * 2))},
        ]
        return {"indicators": radar_indicators}

    def evaluate_fund(self, code: str) -> Dict:
        """综合评测一支基金

        从天天基金获取数据并计算各项指标
        """
        from app.services.fund_data import FundDataService

        result = {
            'code': code,
            'name': '',
            'score': 0,
            'indicators': [],
            'radar_data': {},
            'info': {},
            'valuation': {},
        }

        try:
            # 1. 获取基金基本信息
            fund_info = FundDataService.get_fund_info(code)
            result['name'] = fund_info.get('name', '')
            result['info'] = fund_info

            # 2. 获取历史净值（1年数据用于快速评测）
            nav_df = FundDataService.get_fund_nav(code, days=365)

            if nav_df.empty or len(nav_df) < 30:
                print(f"基金 {code} 净值数据不足")
                return result

            # 3. 计算收益率
            returns_dict = FundDataService.calc_returns(nav_df)

            # 4. 计算每日收益率
            daily_returns = FundDataService.calc_daily_returns(nav_df)

            # 5. 计算风险指标（基于复权净值，避免 ETF 拆分导致异常回撤/波动）
            adj_nav_list = FundDataService._adjusted_nav(nav_df).tolist()
            sharpe = self.calc_sharpe(daily_returns)
            max_drawdown = self.calc_max_drawdown(adj_nav_list)
            volatility = self.calc_volatility(daily_returns)
            profit_prob = self.calc_profit_probability(daily_returns)

            # 6. 获取估值数据
            valuation = FundDataService.get_fund_valuation(code)
            result['valuation'] = valuation

            # 7. 汇总指标
            indicators_dict = {
                **returns_dict,
                'sharpe': sharpe,
                'max_drawdown': max_drawdown,
                'volatility': volatility,
                'profit_prob': profit_prob,
            }

            # 添加估值指标
            if valuation.get('pe'):
                try:
                    indicators_dict['pe'] = float(valuation['pe'])
                except:
                    indicators_dict['pe'] = 0

            if valuation.get('pb'):
                try:
                    indicators_dict['pb'] = float(valuation['pb'])
                except:
                    indicators_dict['pb'] = 0

            if valuation.get('roe'):
                try:
                    indicators_dict['roe'] = float(valuation['roe'].replace('%', ''))
                except:
                    indicators_dict['roe'] = 0

            # 8. 计算综合评分
            score = self.calc_score(indicators_dict)
            result['score'] = score

            # 9. 生成指标列表
            result['indicators'] = self._build_indicators(indicators_dict)

            # 10. 生成雷达图数据
            result['radar_data'] = self.evaluate_radar_data(indicators_dict)

            return result

        except Exception as e:
            print(f"评测基金 {code} 失败: {e}")
            import traceback
            traceback.print_exc()
            return result

    def _build_indicators(self, indicators: Dict[str, float]) -> List[Dict]:
        """构建指标列表"""
        result = []

        # 收益率指标
        for key, label in [('return_1y', '近1年收益'), ('return_3y', '近3年收益'), ('return_5y', '近5年收益')]:
            value = indicators.get(key)
            if value is None:
                result.append({'name': label, 'value': None, 'score': 0, 'type': 'return', 'note': '数据不足'})
            else:
                score = min(100, max(0, int(value * 2 + 50)))
                result.append({'name': label, 'value': value, 'score': score, 'type': 'return'})

        # 风险指标
        sharpe = indicators.get('sharpe', 0) or 0
        sharpe_score = min(100, max(0, int(sharpe * 30 + 50)))
        result.append({'name': '夏普比率', 'value': sharpe, 'score': sharpe_score, 'type': 'risk'})

        sortino = indicators.get('sortino', 0) or 0
        sortino_score = min(100, max(0, int(sortino * 25 + 50)))
        result.append({'name': 'Sortino比率', 'value': sortino, 'score': sortino_score, 'type': 'risk'})

        calmar = indicators.get('calmar', 0) or 0
        calmar_score = min(100, max(0, int(calmar * 30 + 50)))
        result.append({'name': '卡玛比率', 'value': calmar, 'score': calmar_score, 'type': 'risk'})

        max_dd = indicators.get('max_drawdown', 0) or 0
        mdd_score = min(100, max(0, int(100 - abs(max_dd))))
        result.append({'name': '最大回撤', 'value': max_dd, 'score': mdd_score, 'type': 'risk'})

        volatility = indicators.get('volatility', 0) or 0
        vol_score = min(100, max(0, int(100 - volatility * 2)))
        result.append({'name': '年化波动', 'value': volatility, 'score': vol_score, 'type': 'risk'})

        profit_prob = indicators.get('profit_prob', 0) or 0
        prob_score = min(100, max(0, int(profit_prob)))
        result.append({'name': '盈利概率', 'value': profit_prob, 'score': prob_score, 'type': 'risk'})

        # 同类排名百分位
        return_1y_pct = indicators.get('return_1y_pct')
        if return_1y_pct is not None:
            result.append({
                'name': '同类1y百分位',
                'value': return_1y_pct,
                'score': int(return_1y_pct),
                'type': 'rank',
                'note': f'高于{return_1y_pct:.0f}%同类基金',
            })

        return result

    def evaluate_fund_from_df(self, code: str, name: str, fund_info: dict, nav_df,
                              peer_returns: Optional[List[float]] = None) -> Dict:
        """从 DataFrame 评测基金（用于增量更新场景）

        Args:
            code: 基金代码
            name: 基金名称
            fund_info: 基金基本信息
            nav_df: 净值 DataFrame
            peer_returns: 同类基金近 1 年收益率列表（用于百分位排名）
        """
        result = {
            'code': code,
            'name': name,
            'score': 0,
            'indicators': [],
            'radar_data': {},
            'info': fund_info,
            'valuation': {},
        }

        try:
            if nav_df is None or nav_df.empty or len(nav_df) < 30:
                print(f"基金 {code} 净值数据不足")
                return result

            # 1. 计算收益率
            returns_dict = self.calc_returns_from_df(nav_df)

            # 2. 计算每日收益率
            daily_returns = self.calc_daily_returns_from_df(nav_df)

            # 3. 计算风险指标（基于复权净值，避免 ETF 拆分导致异常回撤/波动）
            adj_nav = self._adjusted_nav(nav_df)
            nav_list = adj_nav.tolist()
            sharpe = self.calc_sharpe(daily_returns)
            sortino = self.calc_sortino(daily_returns)
            max_drawdown = self.calc_max_drawdown(nav_list)
            volatility = self.calc_volatility(daily_returns)
            profit_prob = self.calc_profit_probability(daily_returns)
            calmar = self.calc_calmar(returns_dict.get('return_1y') or 0, max_drawdown)

            # 4. 同类百分位
            return_1y_pct = None
            if peer_returns and returns_dict.get('return_1y') is not None:
                return_1y_pct = self.calc_percentile_rank(returns_dict['return_1y'], peer_returns)

            # 5. 汇总指标
            indicators_dict = {
                **returns_dict,
                'sharpe': sharpe,
                'sortino': sortino,
                'calmar': calmar,
                'max_drawdown': max_drawdown,
                'volatility': volatility,
                'profit_prob': profit_prob,
                'return_1y_pct': return_1y_pct,
            }

            # 6. 计算综合评分
            score = self.calc_score(indicators_dict)
            result['score'] = score

            # 7. 生成指标列表
            result['indicators'] = self._build_indicators(indicators_dict)

            # 8. 生成雷达图数据
            result['radar_data'] = self.evaluate_radar_data(indicators_dict)

            # 9. 同类对比信息
            if peer_returns:
                result['peer_info'] = {
                    'sample_size': len(peer_returns),
                    'return_1y_percentile': return_1y_pct,
                    'avg_return_1y': round(sum(peer_returns) / len(peer_returns), 2) if peer_returns else None,
                    'max_return_1y': max(peer_returns) if peer_returns else None,
                    'min_return_1y': min(peer_returns) if peer_returns else None,
                }

            return result

        except Exception as e:
            print(f"评测基金 {code} 失败: {e}")
            import traceback
            traceback.print_exc()
            return result

    @staticmethod
    def _adjusted_nav(nav_df) -> pd.Series:
        """返回复权净值序列。

        优先用 accumulated_nav（ETF 拆分 / 基金分红已复权），
        缺失或无效时回退到 nav。
        """
        import pandas as pd  # lazy（pd.notna runtime）
        if 'accumulated_nav' in nav_df.columns:
            adj = nav_df['accumulated_nav'].where(
                pd.notna(nav_df['accumulated_nav']) & (nav_df['accumulated_nav'] > 0),
                nav_df['nav']
            )
        else:
            adj = nav_df['nav']
        return adj

    def calc_returns_from_df(self, nav_df) -> Dict:
        """从 DataFrame 计算各周期收益率。

        以"今天"为锚点，找 ≤ 今天 的最后一条数据作为 end_date，
        然后以 end_date 往前 365/1095/1825 天作为各周期起点。
        使用 accumulated_nav 进行复权计算；数据不足时返回 None。
        """
        import pandas as pd  # lazy
        result = {'return_1y': None, 'return_3y': None, 'return_5y': None}

        if nav_df is None or nav_df.empty or len(nav_df) < 2:
            return result

        df = nav_df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df['adj_nav'] = self._adjusted_nav(df)

        today = datetime.now().date()
        end_mask = df['date'].dt.date <= today
        if not end_mask.any():
            return result
        end_idx = df[end_mask].index[-1]
        end_date = df.loc[end_idx, 'date']
        end_nav = df.loc[end_idx, 'adj_nav']
        if not end_nav or end_nav <= 0:
            return result

        for days, key in [(365, '1y'), (1095, '3y'), (1825, '5y')]:
            target_start = end_date - timedelta(days=days)
            period = df[(df['date'] >= target_start) & (df['date'] <= end_date)]
            if len(period) < 2:
                result[f'return_{key}'] = None
                continue
            actual_start = period.iloc[0]['date']
            actual_span_days = (end_date - actual_start).days
            if actual_span_days < days * 0.8:
                result[f'return_{key}'] = None
                continue
            start_nav = period.iloc[0]['adj_nav']
            if not start_nav or start_nav <= 0:
                result[f'return_{key}'] = None
                continue
            result[f'return_{key}'] = round((end_nav - start_nav) / start_nav * 100, 2)

        return result

    def calc_daily_returns_from_df(self, nav_df) -> list:
        """从 DataFrame 计算每日收益率（基于复权净值）。"""
        if nav_df.empty or len(nav_df) < 2:
            return []

        nav_df = nav_df.sort_values('date').copy()
        nav_df['adj_nav'] = self._adjusted_nav(nav_df)
        returns = nav_df['adj_nav'].pct_change().dropna().tolist()
        return returns


# 全局服务实例
eval_service = FundEvalService()
