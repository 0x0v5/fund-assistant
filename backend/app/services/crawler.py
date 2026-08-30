"""Data crawler service using Sina Finance API."""

from __future__ import annotations  # 让 pd.DataFrame 等类型注解变字符串，懒求值

from typing import List, Optional
import re
import requests
from datetime import datetime, timedelta
import json


class FundDataService:
    """基金数据服务（基于新浪财经）。"""

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }

    @staticmethod
    def get_etf_hist(code: str, days: int = 90) -> pd.DataFrame:
        """获取 ETF 历史行情（新浪财经）。"""
        import pandas as pd  # lazy: 仅 ETF 抓取路径加载，省启动 ~45MB
        try:
            code_prefix = 'sz' if code.startswith(('15', '16', '18')) else 'sh'

            url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
            params = {
                'symbol': f'{code_prefix}{code}',
                'scale': '240',
                'ma': 'no',
                'datalen': str(days)
            }

            resp = requests.get(url, params=params, headers=FundDataService.HEADERS, timeout=10)
            data = resp.json()

            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df = df.rename(columns={
                'day': 'date',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            return df

        except Exception as e:
            print(f"获取 ETF {code} 历史数据失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_etf_hist_tencent(code: str, days: int = 90) -> pd.DataFrame:
        """获取 ETF 历史行情（腾讯财经），用于与新浪数据交叉验证。"""
        import pandas as pd  # lazy
        try:
            code_prefix = 'sz' if code.startswith(('15', '16', '18')) else 'sh'
            end_date = datetime.now()
            start_date = end_date - timedelta(days=int(days * 1.5) + 30)
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')

            url = 'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
            params = {
                'param': f'{code_prefix}{code},day,{start_str},{end_str},{days + 5},qfq',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/',
            }
            resp = requests.get(url, params=params, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            data = resp.json()

            key = f'{code_prefix}{code}'
            klines = data.get('data', {}).get(key, {}).get('qfqday') or data.get('data', {}).get(key, {}).get('day')
            if not klines:
                print(f"腾讯财经 {code} 无K线数据")
                return pd.DataFrame()

            records = []
            for item in klines:
                if isinstance(item, list) and len(item) >= 5:
                    records.append({
                        'date': item[0],
                        'open': float(item[1]),
                        'close': float(item[2]),
                        'high': float(item[3]),
                        'low': float(item[4]),
                        'volume': float(item[5]) if len(item) > 5 else 0.0,
                    })

            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            if len(df) > days:
                df = df.tail(days).reset_index(drop=True)

            return df

        except Exception as e:
            print(f"获取 ETF {code} 腾讯财经历史数据失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_etf_realtime(code: str) -> dict:
        """获取 ETF 实时盘中行情（新浪 hq.sinajs.cn 接口）。"""
        code_prefix = 'sz' if code.startswith(('15', '16', '18')) else 'sh'

        url = f'https://hq.sinajs.cn/list={code_prefix}{code}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn',
        }

        empty = {
            "code": code, "name": "", "current_price": 0,
            "prev_close": 0, "open": 0, "high": 0, "low": 0,
            "change_pct": 0, "update_time": "", "is_trading": False,
        }

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            text = resp.text.strip()

            m = re.search(r'var hq_str_[a-z]+\d+="([^"]*)"', text)
            if not m:
                return empty
            fields = m.group(1).split(',')
            if len(fields) < 32:
                return empty

            name = fields[0]
            open_p = float(fields[1]) if fields[1] else 0
            prev_close = float(fields[2]) if fields[2] else 0
            current = float(fields[3]) if fields[3] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0
            date_str = fields[30] if len(fields) > 30 else ''
            time_str = fields[31] if len(fields) > 31 else ''
            update_time = f"{date_str} {time_str}" if date_str and time_str else ""

            if prev_close > 0 and current > 0:
                change_pct = round((current - prev_close) / prev_close * 100, 2)
            else:
                change_pct = 0.0

            is_trading = (current > 0 and prev_close > 0)

            return {
                "code": code,
                "name": name,
                "current_price": round(current, 4),
                "prev_close": round(prev_close, 4),
                "open": round(open_p, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "change_pct": change_pct,
                "update_time": update_time,
                "is_trading": is_trading,
            }
        except Exception as e:
            print(f"获取 ETF {code} 实时行情失败: {e}")
            return empty

    @staticmethod
    def adjust_for_splits(prices: pd.Series, threshold: float = 0.30) -> pd.Series:
        """对 ETF 收盘价序列进行后复权（拆分调整）。

        识别单日涨跌幅绝对值超过 threshold 的交易日视为拆分/合并，
        将拆分日之前的价格按比例调整，使序列在拆分点保持连续。

        Args:
            prices: 按日期排序的收盘价序列（index 为日期）
            threshold: 拆分识别阈值，默认 30%（即 |return| > 30%）

        Returns:
            后复权价格序列
        """
        if prices is None or prices.empty:
            return prices

        adjusted = prices.copy().astype(float)
        returns = prices.pct_change().abs()
        split_dates = returns[returns > threshold].index

        for split_date in sorted(split_dates):
            try:
                idx = prices.index.get_loc(split_date)
            except KeyError:
                continue
            if idx <= 0:
                continue

            price_before = float(prices.iloc[idx - 1])
            price_after = float(prices.iloc[idx])
            if price_before <= 0 or price_after <= 0:
                continue

            split_ratio = price_after / price_before
            # 拆分日之前的价格按比例调整，保持序列连续
            adjusted.iloc[:idx] *= split_ratio

        return adjusted

    @staticmethod
    def calc_momentum_from_df(df: pd.DataFrame, code: str, short_window: int = 20, long_window: int = 60) -> dict:
        """从给定 DataFrame 计算 ETF 动量指标（支持多数据源对比）。

        数据约定：
          df 给出的是「截至昨日收盘」的 K 线（新浪 K 线 API 收盘后才有今日 bar）。
          若 df 的最新 bar 日期 < 今天，从实时行情接口取当前价补成今日 bar：
            - 当前价用于 short_return/medium_return/daily_change/above_ma? 比较
            - 但**不参与 ma20/ma60 的 rolling 计算**（今日 bar 还没定型，
              把它纳入会污染参考均线，导致"在60日线下"误判）
        """
        import pandas as pd  # lazy
        if df is None or df.empty or len(df) < 10:
            return {
                "code": code,
                "short_momentum": 0,
                "long_momentum": 0,
                "short_sharpe": 0,
                "above_ma60": False,
                "ma60": 0,
                "current_price": 0,
                "ma20": 0,
                "update_date": None,
            }

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])

        last_date = df.iloc[-1]['date'].date() if pd.notna(df.iloc[-1]['date']) else None
        today = datetime.now().date()

        # 是否需要补今日实时价（盘中时段 K 线没今日 bar）
        need_today_bar = last_date is not None and last_date < today
        current_price_realtime = 0.0
        if need_today_bar:
            rt = FundDataService.get_etf_realtime(code)
            if rt and rt.get("current_price", 0) > 0:
                current_price_realtime = float(rt["current_price"])

        # ma20/ma60 只用「昨日收盘前」的 close 计算（不含今日未定型 bar）
        df['ma20'] = df['close'].rolling(window=short_window).mean()
        df['ma60'] = df['close'].rolling(window=long_window).mean()

        latest = df.iloc[-1]
        prev_close = float(latest['close'])  # 最新一个 bar 的 close（昨日收盘）
        ma20 = float(latest['ma20']) if pd.notna(latest.get('ma20')) else None
        ma60 = float(latest['ma60']) if pd.notna(latest.get('ma60')) else None

        if need_today_bar and current_price_realtime > 0:
            current_price = current_price_realtime
            update_date = today
        else:
            current_price = prev_close
            update_date = last_date

        if len(df) >= short_window + 1:
            short_return = (current_price - df.iloc[-short_window - 1]['close']) / df.iloc[-short_window - 1]['close'] * 100
        else:
            short_return = 0.0

        if len(df) >= long_window + 1:
            long_return = (current_price - df.iloc[-long_window - 1]['close']) / df.iloc[-long_window - 1]['close'] * 100
        else:
            long_return = float(short_return)

        import numpy as np
        daily_returns = df['close'].pct_change()
        # 短期夏普：用「最近 20 个交易日（含今日实时价）」的收益率
        if len(daily_returns) >= short_window:
            # 构造含今日收益的 20 个收益率
            if need_today_bar and prev_close > 0 and current_price_realtime > 0:
                today_return = (current_price_realtime - prev_close) / prev_close
                last_20_returns = list(daily_returns.iloc[-(short_window - 1):]) + [today_return]
            else:
                last_20_returns = list(daily_returns.iloc[-short_window:])
            arr = pd.Series(last_20_returns)
            mean_r = arr.mean()
            std_r = arr.std()
            if std_r and std_r > 0 and not np.isnan(std_r):
                short_sharpe = float(mean_r / std_r * np.sqrt(252))
            else:
                short_sharpe = 0.0
        else:
            short_sharpe = 0.0

        above_ma20 = bool(current_price > ma20) if ma20 is not None else False
        above_ma60 = bool(current_price > ma60) if ma60 is not None else False

        daily_change = 0.0
        if prev_close > 0:
            daily_change = round((current_price - prev_close) / prev_close * 100, 2)

        return {
            "code": code,
            "short_momentum": round(float(short_return), 2),
            "long_momentum": round(float(long_return), 2),
            "short_sharpe": round(short_sharpe, 2),
            "daily_change": daily_change,
            "above_ma20": above_ma20,
            "above_ma60": above_ma60,
            "ma20": round(ma20, 4) if ma20 is not None else 0,
            "ma60": round(ma60, 4) if ma60 is not None else 0,
            "current_price": round(current_price, 4),
            "update_date": str(update_date) if update_date else None,
        }

    @staticmethod
    def calc_momentum(code: str, short_window: int = 20, long_window: int = 60) -> dict:
        """计算 ETF 动量指标（默认新浪数据源）。"""
        df = FundDataService.get_etf_hist(code, days=long_window + 30)
        return FundDataService.calc_momentum_from_df(df, code, short_window, long_window)

    @staticmethod
    def calc_momentum_tencent(code: str, short_window: int = 20, long_window: int = 60) -> dict:
        """计算 ETF 动量指标（腾讯数据源），用于与新浪交叉验证。"""
        df = FundDataService.get_etf_hist_tencent(code, days=long_window + 30)
        return FundDataService.calc_momentum_from_df(df, code, short_window, long_window)

    @staticmethod
    def get_fund_nav(fund_code: str) -> pd.DataFrame:
        """获取场外基金净值数据."""
        import pandas as pd  # lazy（占位实现，仅返回空表）
        # TODO: 实现场外基金净值获取
        return pd.DataFrame()


class QdiiQuotaService:
    """QDII 额度查询服务（场外基金）。

    数据来源：天天基金历史净值页面（含申购状态）
    """

    # ETF联接基金（6只）
    ETF_LINK_FUNDS = {
        "018064": "华夏标普500ETF发起式联接(QDII)A",
        "018065": "华夏标普500ETF发起式联接(QDII)C",
        "050025": "博时标普500ETF联接A",
        "006075": "华夏标普500指数",
        "017028": "国泰标普500ETF发起联接(QDII)A",
        "017030": "国泰标普500ETF发起联接(QDII)C",
    }

    # FOF基金（3只）
    FOF_FUNDS = {
        "007721": "天弘标普500发起(QDII-FOF)A",
        "007722": "天弘标普500发起(QDII-FOF)C",
        "022523": "天弘标普500发起(QDII-FOF)D",
    }

    # 股票指数/LOF基金（4只）
    INDEX_FUNDS = {
        "017641": "摩根标普500指数(QDII)人民币A",
        "019305": "摩根标普500指数(QDII)人民币C",
        "161125": "易方达标普500指数人民币A",
        "012860": "易方达标普500指数人民币C",
    }

    # 纳斯达克100 ETF联接基金（12只）
    NDX_ETF_LINK_FUNDS = {
        "270042": "广发纳指100ETF联接(QDII)A",
        "006479": "广发纳指100ETF联接(QDII)C",
        "021778": "广发纳指100ETF联接(QDII)F",
        "000834": "大成纳指100ETF联接(QDII)A",
        "040046": "华安纳指100ETF联接(QDII)A",
        "161130": "易方达纳指100ETF联接(QDII-LOF)A",
        "015299": "华夏纳指100ETF联接(QDII)A",
        "016055": "博时纳指100ETF联接(QDII)A",
        "019524": "华泰柏瑞纳指100ETF联接(QDII)A",
        "018966": "汇添富纳指100ETF联接(QDII)A",
        "019547": "招商纳指100ETF联接(QDII)A",
        "016532": "嘉实纳指100ETF联接(QDII)A",
    }

    # 纳斯达克100 直接指数QDII（9只）
    NDX_DIRECT_FUNDS = {
        "019172": "摩根纳斯达克100指数(QDII)人民币A",
        "019441": "万家纳指100指数(QDII)A",
        "160213": "国泰纳斯达克100指数(QDII)",
        "539001": "建信纳斯达克100指数(QDII)",
        "018043": "天弘纳指100指数发起(QDII)A",
        "019736": "宝盈纳指100指数发起(QDII)A",
        "016452": "南方纳指100指数发起(QDII)A",
        "021000": "南方纳指100指数发起(QDII)I",
    }

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://fund.eastmoney.com/',
    }

    HEADERS_F10 = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://fundf10.eastmoney.com/',
    }

    # 缓存
    _quota_cache = {}
    _last_update = None
    _cache_duration = 300  # 5分钟缓存

    @staticmethod
    def _fetch_quota_from_tiantian(code: str) -> tuple:
        """从天天基金获取单只基金的限额状态。

        Returns:
            (apply_status, redeem_status, nav_date)
        """
        import re
        import requests

        url = 'https://fund.eastmoney.com/f10/F10DataApi.aspx'
        params = {
            'type': 'lsjz',
            'code': code,
            'page': 1,
            'per': 1,
        }

        try:
            resp = requests.get(url, params=params, headers=QdiiQuotaService.HEADERS, timeout=10)
            # 提取所有 <td> 内容
            tds = re.findall(r'<td[^>]*>([^<]*)</td>', resp.text)
            # 表格列: 净值日期, 单位净值, 累计净值, 日增长率, 申购状态, 赎回状态, 分红送配
            if len(tds) >= 6:
                return tds[4], tds[5], tds[0]  # 申购状态, 赎回状态, 净值日期
            return None, None, None
        except Exception as e:
            print(f"获取 {code} 净值数据失败: {e}")
            return None, None, None

    @staticmethod
    def _fetch_limit_from_eastmoney(code: str) -> tuple:
        """从东方财富 F10 获取限购金额和基金档案。

        Returns:
            (apply_status, limit_amount, redeem_status, fund_info)
            fund_info: {manager, scale, found_date, m_fee, t_fee, buy_fee, redeem_fee}
        """
        import re
        import requests

        fund_info = {
            "manager": "",
            "scale": "",
            "found_date": "",
            "m_fee": "",
            "t_fee": "",
            "buy_fee": "",
            "redeem_fee": "",
        }

        url = f'https://fundf10.eastmoney.com/{code}.html'

        try:
            resp = requests.get(url, headers=QdiiQuotaService.HEADERS_F10, timeout=10)
            content = resp.text

            # 提取申购状态
            apply_status = '未知'
            if '暂停申购' in content:
                apply_status = '暂停申购'
            elif '限大额' in content:
                apply_status = '限大额'
            elif '开放申购' in content:
                apply_status = '开放申购'

            # 提取限购金额
            limit_amount = ''
            patterns = [
                r'单日累计购买上限(\d+)',
                r'单笔申购上限(\d+)',
                r'单日累计申购上限(\d+)',
            ]
            for p in patterns:
                match = re.search(p, content)
                if match:
                    limit_amount = match.group(1)
                    break

            # 提取赎回状态
            redeem_status = '未知'
            if '开放赎回' in content:
                redeem_status = '开放赎回'
            elif '暂停赎回' in content:
                redeem_status = '暂停赎回'

            # 提取净资产规模（排除 HTML 标签）
            scale_match = re.search(r'净资产规模：\s*<[^>]+>\s*([^<（]+)', content)
            if scale_match:
                fund_info["scale"] = scale_match.group(1).strip()

            # 提取成立日期
            date_match = re.search(r'成立日期：\s*<span>([^<]+)', content)
            if date_match:
                fund_info["found_date"] = date_match.group(1).strip()

            # 提取基金经理
            manager_match = re.search(r'基金经理：\s*<a[^>]*>([^<]+)', content)
            if manager_match:
                fund_info["manager"] = manager_match.group(1).strip()

            # 提取管理费率
            m_fee_match = re.search(r'>管理费率</th><td>([\d.]+%)', content)
            if m_fee_match:
                fund_info["m_fee"] = m_fee_match.group(1).strip()

            # 提取托管费率
            t_fee_match = re.search(r'>托管费率</th><td>([\d.]+%)', content)
            if t_fee_match:
                fund_info["t_fee"] = t_fee_match.group(1).strip()

            # 提取申购费率（使用更精确的模式）
            buy_fee_match = re.search(r'最高申购费率.*?<td[^>]*>([\d.]+%)', content, re.DOTALL)
            if buy_fee_match:
                fund_info["buy_fee"] = buy_fee_match.group(1).strip()

            # 提取赎回费率
            redeem_fee_match = re.search(r'最高赎回费率.*?<td[^>]*>([\d.]+%)', content, re.DOTALL)
            if redeem_fee_match:
                fund_info["redeem_fee"] = redeem_fee_match.group(1).strip()

            return apply_status, limit_amount, redeem_status, fund_info
        except Exception as e:
            print(f"获取 {code} F10数据失败: {e}")
            return '未知', '', '未知', fund_info

    @staticmethod
    def _fetch_fund_info_from_tiantian(code: str) -> dict:
        """从天天基金档案页获取基金详细信息（基金经理、规模等）。

        Returns:
            {manager, manager_exp, scale, found_date, m_fee, t_fee}
        """
        import re
        import requests

        url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'
        fund_info = {
            "manager": "",
            "manager_exp": "",
            "scale": "",
            "found_date": "",
            "m_fee": "",
            "t_fee": "",
        }

        try:
            resp = requests.get(url, headers=QdiiQuotaService.HEADERS, timeout=10)
            content = resp.text

            # 提取基金经理
            manager_match = re.search(r'"name":"([^"]+)"[^}]*"star"', content)
            if manager_match:
                fund_info["manager"] = manager_match.group(1)

            # 提取基金经理任职时间
            exp_match = re.search(r'"workTime":"([^"]+)"', content)
            if exp_match:
                fund_info["manager_exp"] = exp_match.group(1)

            # 提取基金规模
            scale_match = re.search(r'"FundScale":"([^"]+)"', content)
            if scale_match:
                fund_info["scale"] = scale_match.group(1)

            # 提取成立日期
            date_match = re.search(r'"FoundDate":"([^"]+)"', content)
            if date_match:
                fund_info["found_date"] = date_match.group(1)

            # 提取管理费率
            m_fee_match = re.search(r'"MFee":"([^"]+)"', content)
            if m_fee_match:
                fund_info["m_fee"] = m_fee_match.group(1)

            # 提取托管费率
            t_fee_match = re.search(r'"TFee":"([^"]+)"', content)
            if t_fee_match:
                fund_info["t_fee"] = t_fee_match.group(1)

        except Exception as e:
            print(f"获取 {code} 基金档案失败: {e}")

        return fund_info

    @classmethod
    def _parse_quota_status(cls, apply_status: str, redeem_status: str) -> str:
        """解析限额状态文本。

        转换为统一的状态描述：
        - 开放申购 -> 正常
        - 限制大额申购 -> 限额
        - 暂停申购 -> 限购
        """
        if not apply_status:
            return "未知"

        if "暂停" in apply_status:
            return "限购"
        elif "限制" in apply_status:
            return "限额"
        elif "开放" in apply_status:
            return "正常"
        else:
            return apply_status

    @classmethod
    def get_qdii_quota(cls, force: bool = False) -> List[dict]:
        """获取所有 QDII 场外基金限额状态。

        从东方财富 F10 获取限购金额，天天基金获取净值数据。
        按用户分类：ETF联接基金、FOF基金、股票指数/LOF

        Args:
            force: 是否跳过缓存强制重新抓取（refresh 接口用）。
        """
        import time

        now = time.time()
        # 检查缓存
        if not force:
            if cls._quota_cache and cls._last_update:
                if now - cls._last_update < cls._cache_duration:
                    return list(cls._quota_cache.values())

        results = []

        # ETF联接基金（6只）
        for code, name in cls.ETF_LINK_FUNDS.items():
            # 从东方财富 F10 获取限购状态、金额和基金档案
            apply_status, limit_amount, redeem_status, f10_info = cls._fetch_limit_from_eastmoney(code)
            quota_status = cls._parse_quota_status(apply_status, redeem_status)

            # 从天天基金获取净值日期和基金档案
            _, _, nav_date = cls._fetch_quota_from_tiantian(code)
            tt_info = cls._fetch_fund_info_from_tiantian(code)
            # 合并两个来源的基金档案，F10 的费率数据优先级更高
            fund_info = {**tt_info, **f10_info}

            results.append({
                "code": code,
                "name": name,
                "type": "ETF联接基金",
                "quota_status": quota_status,
                "apply_status": apply_status,
                "limit_amount": limit_amount,
                "redeem_status": redeem_status,
                "nav_date": nav_date,
                "manager": fund_info.get("manager", ""),
                "manager_exp": fund_info.get("manager_exp", ""),
                "scale": fund_info.get("scale", ""),
                "found_date": fund_info.get("found_date", ""),
                "m_fee": fund_info.get("m_fee", ""),
                "t_fee": fund_info.get("t_fee", ""),
                "buy_fee": fund_info.get("buy_fee", ""),
                "redeem_fee": fund_info.get("redeem_fee", ""),
                "update_time": datetime.now().isoformat(),
            })

        # FOF基金（3只）
        for code, name in cls.FOF_FUNDS.items():
            apply_status, limit_amount, redeem_status, f10_info = cls._fetch_limit_from_eastmoney(code)
            quota_status = cls._parse_quota_status(apply_status, redeem_status)
            _, _, nav_date = cls._fetch_quota_from_tiantian(code)
            tt_info = cls._fetch_fund_info_from_tiantian(code)
            fund_info = {**tt_info, **f10_info}

            results.append({
                "code": code,
                "name": name,
                "type": "FOF基金",
                "quota_status": quota_status,
                "apply_status": apply_status,
                "limit_amount": limit_amount,
                "redeem_status": redeem_status,
                "nav_date": nav_date,
                "manager": fund_info.get("manager", ""),
                "manager_exp": fund_info.get("manager_exp", ""),
                "scale": fund_info.get("scale", ""),
                "found_date": fund_info.get("found_date", ""),
                "m_fee": fund_info.get("m_fee", ""),
                "t_fee": fund_info.get("t_fee", ""),
                "buy_fee": fund_info.get("buy_fee", ""),
                "redeem_fee": fund_info.get("redeem_fee", ""),
                "update_time": datetime.now().isoformat(),
            })

        # 股票指数/LOF基金（4只）
        for code, name in cls.INDEX_FUNDS.items():
            apply_status, limit_amount, redeem_status, f10_info = cls._fetch_limit_from_eastmoney(code)
            quota_status = cls._parse_quota_status(apply_status, redeem_status)
            _, _, nav_date = cls._fetch_quota_from_tiantian(code)
            tt_info = cls._fetch_fund_info_from_tiantian(code)
            fund_info = {**tt_info, **f10_info}

            results.append({
                "code": code,
                "name": name,
                "type": "股票指数/LOF",
                "quota_status": quota_status,
                "apply_status": apply_status,
                "limit_amount": limit_amount,
                "redeem_status": redeem_status,
                "nav_date": nav_date,
                "manager": fund_info.get("manager", ""),
                "manager_exp": fund_info.get("manager_exp", ""),
                "scale": fund_info.get("scale", ""),
                "found_date": fund_info.get("found_date", ""),
                "m_fee": fund_info.get("m_fee", ""),
                "t_fee": fund_info.get("t_fee", ""),
                "buy_fee": fund_info.get("buy_fee", ""),
                "redeem_fee": fund_info.get("redeem_fee", ""),
                "update_time": datetime.now().isoformat(),
            })

        # 纳斯达克100 ETF联接基金（12只）
        for code, name in cls.NDX_ETF_LINK_FUNDS.items():
            apply_status, limit_amount, redeem_status, f10_info = cls._fetch_limit_from_eastmoney(code)
            quota_status = cls._parse_quota_status(apply_status, redeem_status)
            _, _, nav_date = cls._fetch_quota_from_tiantian(code)
            tt_info = cls._fetch_fund_info_from_tiantian(code)
            fund_info = {**tt_info, **f10_info}

            results.append({
                "code": code,
                "name": name,
                "type": "纳指100 ETF联接",
                "quota_status": quota_status,
                "apply_status": apply_status,
                "limit_amount": limit_amount,
                "redeem_status": redeem_status,
                "nav_date": nav_date,
                "manager": fund_info.get("manager", ""),
                "manager_exp": fund_info.get("manager_exp", ""),
                "scale": fund_info.get("scale", ""),
                "found_date": fund_info.get("found_date", ""),
                "m_fee": fund_info.get("m_fee", ""),
                "t_fee": fund_info.get("t_fee", ""),
                "buy_fee": fund_info.get("buy_fee", ""),
                "redeem_fee": fund_info.get("redeem_fee", ""),
                "update_time": datetime.now().isoformat(),
            })

        # 纳斯达克100 直接指数QDII（8只）
        for code, name in cls.NDX_DIRECT_FUNDS.items():
            apply_status, limit_amount, redeem_status, f10_info = cls._fetch_limit_from_eastmoney(code)
            quota_status = cls._parse_quota_status(apply_status, redeem_status)
            _, _, nav_date = cls._fetch_quota_from_tiantian(code)
            tt_info = cls._fetch_fund_info_from_tiantian(code)
            fund_info = {**tt_info, **f10_info}

            results.append({
                "code": code,
                "name": name,
                "type": "纳指100 直接指数",
                "quota_status": quota_status,
                "apply_status": apply_status,
                "limit_amount": limit_amount,
                "redeem_status": redeem_status,
                "nav_date": nav_date,
                "manager": fund_info.get("manager", ""),
                "manager_exp": fund_info.get("manager_exp", ""),
                "scale": fund_info.get("scale", ""),
                "found_date": fund_info.get("found_date", ""),
                "m_fee": fund_info.get("m_fee", ""),
                "t_fee": fund_info.get("t_fee", ""),
                "buy_fee": fund_info.get("buy_fee", ""),
                "redeem_fee": fund_info.get("redeem_fee", ""),
                "update_time": datetime.now().isoformat(),
            })

        # 更新缓存
        cls._quota_cache = {r["code"]: r for r in results}
        cls._last_update = now

        return results

    @classmethod
    def get_etf_link_funds(cls) -> List[dict]:
        """获取ETF联接基金列表。"""
        return [
            {"code": code, "name": name, "type": "ETF联接基金"}
            for code, name in cls.ETF_LINK_FUNDS.items()
        ]

    @classmethod
    def get_fof_funds(cls) -> List[dict]:
        """获取FOF基金列表。"""
        return [
            {"code": code, "name": name, "type": "FOF基金"}
            for code, name in cls.FOF_FUNDS.items()
        ]

    @classmethod
    def get_index_funds(cls) -> List[dict]:
        """获取股票指数/LOF基金列表。"""
        return [
            {"code": code, "name": name, "type": "股票指数/LOF"}
            for code, name in cls.INDEX_FUNDS.items()
        ]

    @classmethod
    def get_ndx_etf_link_funds(cls) -> List[dict]:
        """获取纳斯达克100 ETF联接基金列表。"""
        return [
            {"code": code, "name": name, "type": "纳指100 ETF联接"}
            for code, name in cls.NDX_ETF_LINK_FUNDS.items()
        ]

    @classmethod
    def get_ndx_direct_funds(cls) -> List[dict]:
        """获取纳斯达克100 直接指数QDII基金列表。"""
        return [
            {"code": code, "name": name, "type": "纳指100 直接指数"}
            for code, name in cls.NDX_DIRECT_FUNDS.items()
        ]


# 全局服务实例
fund_data = FundDataService()
qdii_quota = QdiiQuotaService()
