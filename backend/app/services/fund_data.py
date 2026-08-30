"""基金数据获取服务 - 从天天基金、东方财富获取真实数据"""

from __future__ import annotations  # 类型注解懒求值，pandas 可懒加载

import re
import warnings
import requests
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 抑制 SSL 警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


class FundDataService:
    """基金数据获取服务"""

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://fund.eastmoney.com/',
    }

    HEADERS_F10 = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://fundf10.eastmoney.com/',
    }

    @staticmethod
    async def get_fund_nav_async(code: str, days: int = 1825) -> pd.DataFrame:
        """异步获取基金历史净值（httpx）。

        与同步版同语义，但不会阻塞 FastAPI 事件循环。
        """
        import pandas as pd  # lazy
        all_data = []
        page = 1
        max_pages = 100
        empty_pages = 0
        cutoff_date = datetime.now() - timedelta(days=days)

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            while page <= max_pages:
                url = 'https://fund.eastmoney.com/f10/F10DataApi.aspx'
                params = {
                    'type': 'lsjz', 'code': code,
                    'page': str(page), 'per': '20',
                }
                try:
                    resp = await client.get(url, params=params, headers=FundDataService.HEADERS)
                    content = resp.text
                except Exception as e:
                    print(f"获取基金 {code} 第 {page} 页异常: {e}")
                    break

                match = re.search(r'content:"(.*?)"', content, re.DOTALL)
                if not match:
                    break
                html_content = match.group(1)
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.DOTALL)

                if len(rows) <= 1:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                    page += 1
                    continue
                empty_pages = 0

                stop = False
                for row in rows[1:]:
                    cells = re.findall(r'<td[^>]*>([^<]*)</td>', row)
                    if len(cells) >= 3:
                        date_str = cells[0].strip()
                        nav = cells[1].strip()
                        accum_nav = cells[2].strip() if len(cells) > 2 else nav
                        if date_str and nav and nav != 'null':
                            try:
                                record_date = datetime.strptime(date_str, '%Y-%m-%d')
                                if record_date < cutoff_date:
                                    stop = True
                                    break
                            except Exception:
                                pass
                            all_data.append({
                                'date': date_str,
                                'nav': float(nav) if nav else 0,
                                'accumulated_nav': float(accum_nav) if accum_nav and accum_nav != 'null' else None,
                            })

                if stop or empty_pages >= 2:
                    break
                page += 1

        df = pd.DataFrame(all_data)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
        return df

    @staticmethod
    async def get_fund_nav_full_async(code: str) -> pd.DataFrame:
        """从 akshare 拉取基金成立以来全量净值（带累计净值）。

        失败 / 超时回退到 eastmoney 7300 天（20 年）。
        返回列：date, nav, accumulated_nav（与 get_fund_nav_async 形状一致）。
        """
        import pandas as pd  # lazy
        import akshare as ak  # lazy: 仅本函数用到时加载 ~10MB

        async def _fetch(indicator: str):
            return await asyncio.wait_for(
                asyncio.to_thread(
                    ak.fund_open_fund_info_em, symbol=code, indicator=indicator,
                ),
                timeout=60.0,
            )

        try:
            # 串行：akshare 底层 V8 (libmini_racer) 非线程安全，并发会崩溃
            unit_df = await _fetch('单位净值走势')
            accum_df = await _fetch('累计净值走势')
            if unit_df is None or unit_df.empty:
                raise ValueError("akshare returned empty unit NAV")

            result = pd.DataFrame({
                'date': pd.to_datetime(unit_df['净值日期']),
                'nav': pd.to_numeric(unit_df['单位净值'], errors='coerce'),
            })
            if accum_df is not None and not accum_df.empty and '累计净值' in accum_df.columns:
                accum = pd.DataFrame({
                    'date': pd.to_datetime(accum_df['净值日期']),
                    'accumulated_nav': pd.to_numeric(accum_df['累计净值'], errors='coerce'),
                }).drop_duplicates('date', keep='last')
                result = result.merge(accum, on='date', how='left')

            result = result.dropna(subset=['nav'])
            result['accumulated_nav'] = result['accumulated_nav'].fillna(result['nav'])
            result = result.sort_values('date').reset_index(drop=True)
            return result[['date', 'nav', 'accumulated_nav']]

        except Exception as e:
            print(f"[warn] get_fund_nav_full_async({code}) akshare 失败, fallback: {e}")
            return await FundDataService.get_fund_nav_async(code, days=7300)

    @staticmethod
    async def get_fund_info_async(code: str) -> Dict:
        """异步获取基金基本信息（httpx）。"""
        info: Dict = {
            'name': '', 'scale': '', 'found_date': '',
            'm_fee': '', 't_fee': '',
            'manager': '', 'manager_exp': '', 'fund_type': '',
        }
        url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'
        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
                resp = await client.get(url, headers=FundDataService.HEADERS)
                content = resp.text

            name_match = re.search(r'fS_name\s*=\s*"([^"]+)"', content)
            if not name_match:
                name_match = re.search(r'"name":"([^"]+)"', content)
            if name_match:
                info['name'] = name_match.group(1)

            scale_match = re.search(r'fS_amount\s*=\s*"([^"]+)"', content)
            if not scale_match:
                scale_match = re.search(r'"FundScale":"([^"]+)"', content)
            if scale_match:
                info['scale'] = scale_match.group(1)

            date_match = re.search(r'"FoundDate":"([^"]+)"', content)
            if not date_match:
                date_match = re.search(r'fS_setUpDate\s*=\s*"([^"]+)"', content)
            if date_match:
                info['found_date'] = date_match.group(1)

            m_fee_match = re.search(r'"MFee":"([^"]+)"', content)
            if not m_fee_match:
                m_fee_match = re.search(r'fund_Rate\s*=\s*"([^"]+)"', content)
            if m_fee_match:
                info['m_fee'] = m_fee_match.group(1)

            t_fee_match = re.search(r'"TFee":"([^"]+)"', content)
            if t_fee_match:
                info['t_fee'] = t_fee_match.group(1)

            manager_match = re.search(r'"name":"([^"]+)"[^}]*"star"', content)
            if manager_match:
                info['manager'] = manager_match.group(1)

            exp_match = re.search(r'"workTime":"([^"]+)"', content)
            if exp_match:
                info['manager_exp'] = exp_match.group(1)

            type_match = re.search(r'"FundType":"?(\d{3})"?', content)
            if type_match:
                info['fund_type'] = type_match.group(1)
        except Exception as e:
            print(f"异步获取基金 {code} 信息失败: {e}")
        return info

    @staticmethod
    def get_fund_nav(code: str, days: int = 1825) -> pd.DataFrame:
        """获取基金历史净值数据

        Args:
            code: 基金代码
            days: 获取天数（默认5年）

        Returns:
            DataFrame，包含 date, nav, accumulated_nav 列
        """
        import pandas as pd  # lazy
        import requests
        from urllib.parse import urlencode
        from datetime import datetime, timedelta

        all_data = []
        page = 1
        max_pages = 100  # 最多获取 100 页
        empty_pages = 0  # 连续空页计数器
        cutoff_date = datetime.now() - timedelta(days=days)  # 计算截止日期

        while page <= max_pages:
            url = 'https://fund.eastmoney.com/f10/F10DataApi.aspx'
            params = {
                'type': 'lsjz',
                'code': code,
                'page': str(page),
                'per': '20',  # 天天基金每页固定返回20条
            }

            try:
                resp = requests.get(url, params=params, headers=FundDataService.HEADERS, timeout=30,
                                 allow_redirects=True, verify=False)
                content = resp.text

                # 解析 JSONP 格式: var apidata={ content:"..." }
                match = re.search(r'content:"(.*?)"', content, re.DOTALL)
                if not match:
                    break

                html_content = match.group(1)

                # 解析 HTML 表格
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.DOTALL)

                if len(rows) <= 1:  # 只有表头，无数据
                    empty_pages += 1
                    if empty_pages >= 2:  # 连续2页无数据，停止
                        break
                    page += 1
                    continue

                empty_pages = 0  # 重置计数器

                for row in rows[1:]:  # 跳过表头
                    cells = re.findall(r'<td[^>]*>([^<]*)</td>', row)
                    if len(cells) >= 3:
                        date_str = cells[0].strip()
                        nav = cells[1].strip()
                        accum_nav = cells[2].strip() if len(cells) > 2 else nav

                        if date_str and nav and nav != 'null':
                            # 检查是否早于截止日期
                            try:
                                record_date = datetime.strptime(date_str, '%Y-%m-%d')
                                if record_date < cutoff_date:
                                    # 数据已超过截止日期，可以停止获取
                                    empty_pages = 2  # 设置为2以退出循环
                                    break
                            except:
                                pass

                            all_data.append({
                                'date': date_str,
                                'nav': float(nav) if nav else 0,
                                'accumulated_nav': float(accum_nav) if accum_nav and accum_nav != 'null' else None,
                            })

                if empty_pages >= 2:
                    break

                page += 1

            except Exception as e:
                print(f"获取基金 {code} 第 {page} 页净值数据失败: {e}")
                break

        df = pd.DataFrame(all_data)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df = df.reset_index(drop=True)

        return df

    @staticmethod
    def get_fund_info(code: str) -> Dict:
        """获取基金基本信息。

        Returns:
            dict，包含 name, scale, found_date, m_fee, t_fee, manager, manager_exp, fund_type 等
        """
        info: Dict = {
            'name': '',
            'scale': '',
            'found_date': '',
            'm_fee': '',
            't_fee': '',
            'manager': '',
            'manager_exp': '',
            'fund_type': '',
        }

        # 来源 1: 天天基金 pingzhongdata JS（基本信息最完整）
        try:
            url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'
            resp = requests.get(url, headers=FundDataService.HEADERS, timeout=10, verify=False)
            content = resp.text

            name_match = re.search(r'fS_name\s*=\s*"([^"]+)"', content)
            if not name_match:
                name_match = re.search(r'"name":"([^"]+)"', content)
            if name_match:
                info['name'] = name_match.group(1)

            scale_match = re.search(r'fS_amount\s*=\s*"([^"]+)"', content)
            if not scale_match:
                scale_match = re.search(r'"FundScale":"([^"]+)"', content)
            if scale_match:
                info['scale'] = scale_match.group(1)

            date_match = re.search(r'"FoundDate":"([^"]+)"', content)
            if not date_match:
                date_match = re.search(r'fS_setUpDate\s*=\s*"([^"]+)"', content)
            if date_match:
                info['found_date'] = date_match.group(1)

            m_fee_match = re.search(r'"MFee":"([^"]+)"', content)
            if not m_fee_match:
                m_fee_match = re.search(r'fund_Rate\s*=\s*"([^"]+)"', content)
            if m_fee_match:
                info['m_fee'] = m_fee_match.group(1)

            t_fee_match = re.search(r'"TFee":"([^"]+)"', content)
            if t_fee_match:
                info['t_fee'] = t_fee_match.group(1)

            manager_match = re.search(r'"name":"([^"]+)"[^}]*"star"', content)
            if manager_match:
                info['manager'] = manager_match.group(1)

            exp_match = re.search(r'"workTime":"([^"]+)"', content)
            if exp_match:
                info['manager_exp'] = exp_match.group(1)

            # FundType 编码（001=股票型、002=混合型、003=债券型、004=指数型...）
            type_match = re.search(r'"FundType":"?(\d{3})"?', content)
            if type_match:
                info['fund_type'] = type_match.group(1)
        except Exception as e:
            print(f"获取基金 {code} 基本信息（天天基金）失败: {e}")

        return info

    @staticmethod
    def get_fund_valuation(code: str) -> Dict:
        """获取基金估值数据（PE、PB、ROE）

        从东方财富获取
        """
        url = f'https://fundf10.eastmoney.com/jjz_{code}.html'

        try:
            resp = requests.get(url, headers=FundDataService.HEADERS_F10, timeout=15)
            content = resp.text

            valuation = {
                'pe': '',
                'pb': '',
                'roe': '',
            }

            # 解析 PE
            pe_match = re.search(r'市盈率\s*\(PE\)\s*</td><td>([^<]+)', content)
            if pe_match:
                valuation['pe'] = pe_match.group(1).strip()

            # 解析 PB
            pb_match = re.search(r'市净率\s*\(PB\)\s*</td><td>([^<]+)', content)
            if pb_match:
                valuation['pb'] = pb_match.group(1).strip()

            # 解析 ROE
            roe_match = re.search(r'净资产收益率\s*\(ROE\)\s*</td><td>([^<]+)', content)
            if roe_match:
                valuation['roe'] = roe_match.group(1).strip()

            return valuation

        except Exception as e:
            print(f"获取基金 {code} 估值数据失败: {e}")
            return {}

    @staticmethod
    def get_fund_holder_info(code: str) -> Dict:
        """获取基金持仓信息（重仓股等）"""
        url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'

        try:
            resp = requests.get(url, headers=FundDataService.HEADERS, timeout=15, verify=False)
            content = resp.text

            holder_info = {
                'top_stocks': [],
                'industry_allocation': {},
            }

            # 提取重仓股
            stocks_match = re.search(r'"Data_PortfolioWeight"\s*:\s*(\[.*?\])', content, re.DOTALL)
            if stocks_match:
                # 简化处理，实际可能需要更复杂的 JSON 解析
                holder_info['top_stocks'] = []

            return holder_info

        except Exception as e:
            print(f"获取基金 {code} 持仓信息失败: {e}")
            return {}

    @staticmethod
    def _adjusted_nav(nav_df: pd.DataFrame) -> pd.Series:
        """返回复权净值序列：优先 accumulated_nav，缺失/无效则回退 nav。"""
        import pandas as pd  # lazy（pd.notna runtime）
        if 'accumulated_nav' in nav_df.columns:
            return nav_df['accumulated_nav'].where(
                pd.notna(nav_df['accumulated_nav']) & (nav_df['accumulated_nav'] > 0),
                nav_df['nav']
            )
        return nav_df['nav']

    @staticmethod
    def calc_returns(nav_df: pd.DataFrame, periods: List[int] = [365, 1095, 1825]) -> Dict:
        """计算不同周期的收益率（基于复权净值）"""
        if nav_df.empty or len(nav_df) < 2:
            return {'return_1y': 0, 'return_3y': 0, 'return_5y': 0}

        returns = {}
        now = nav_df['date'].max()
        adj_nav = FundDataService._adjusted_nav(nav_df)

        for days, key in [(365, '1y'), (1095, '3y'), (1825, '5y')]:
            start_date = now - timedelta(days=days)
            period_df = nav_df[nav_df['date'] >= start_date]
            adj_period = adj_nav[nav_df['date'] >= start_date]

            if len(period_df) >= 2:
                start_nav = adj_period.iloc[0]
                end_nav = adj_period.iloc[-1]
                if start_nav > 0:
                    returns[f'return_{key}'] = round((end_nav - start_nav) / start_nav * 100, 2)
                else:
                    returns[f'return_{key}'] = 0
            else:
                returns[f'return_{key}'] = 0

        return returns

    @staticmethod
    def calc_daily_returns(nav_df: pd.DataFrame) -> List[float]:
        """计算每日收益率（基于复权净值）"""
        if nav_df.empty or len(nav_df) < 2:
            return []

        nav_df = nav_df.sort_values('date').copy()
        adj_nav = FundDataService._adjusted_nav(nav_df)
        returns = adj_nav.pct_change().dropna().tolist()
        return returns

    @staticmethod
    def search_funds(keyword: str) -> List[Dict]:
        """搜索基金。

        数据源：东方财富 fundsuggest 接口（搜索框背后的 API）。
        实测可靠，返回结构: {"Datas": [{... "FCODE", "SHORTNAME", "FundBaseInfo": {...}}, ...]}
        """
        if not keyword or not keyword.strip():
            return []

        url = 'https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx'
        params = {'m': '1', 'key': keyword.strip()}

        try:
            resp = requests.get(url, params=params, headers=FundDataService.HEADERS, timeout=10)
            data = resp.json()
            results = []
            for item in (data.get('Datas') or [])[:10]:
                base = item.get('FundBaseInfo') or {}
                code = base.get('FCODE') or item.get('CODE') or ''
                name = base.get('SHORTNAME') or item.get('NAME') or ''
                # FundType 编码 → 中文
                ftype_code = base.get('FUNDTYPE', '')
                ftype_map = {
                    '001': '股票型', '002': '混合型', '003': '债券型',
                    '004': '指数型', '005': 'ETF', '006': 'LOF', '007': 'QDII',
                }
                ftype = ftype_map.get(ftype_code, ftype_code)
                results.append({'code': code, 'name': name, 'type': ftype})
            return results

        except Exception as e:
            print(f"搜索基金失败: {e}")
            return []

    @staticmethod
    async def save_fund_info(code: str, info: Dict) -> None:
        """保存基金基本信息到 fund_info 表。"""
        from app.db.database import execute_update

        if not info:
            return
        await execute_update("""
            INSERT INTO fund_info
                (code, name, scale, found_date, m_fee, t_fee, manager, manager_exp, fund_type, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                scale = excluded.scale,
                found_date = excluded.found_date,
                m_fee = excluded.m_fee,
                t_fee = excluded.t_fee,
                manager = excluded.manager,
                manager_exp = excluded.manager_exp,
                fund_type = excluded.fund_type,
                updated_at = excluded.updated_at
        """, (
            code,
            info.get('name', ''),
            info.get('scale', ''),
            info.get('found_date', ''),
            info.get('m_fee', ''),
            info.get('t_fee', ''),
            info.get('manager', ''),
            info.get('manager_exp', ''),
            info.get('fund_type', ''),
            datetime.now().isoformat(),
        ))

    @staticmethod
    async def get_fund_info_cached(code: str) -> Dict:
        """获取基金基本信息：先查 DB，缺失再调 API 并落库。"""
        from app.db.database import execute_query

        # 1. 查 DB
        try:
            rows = await execute_query("SELECT * FROM fund_info WHERE code = ?", (code,))
            if rows:
                r = rows[0]
                return {
                    'name': r.get('name', ''),
                    'scale': r.get('scale', ''),
                    'found_date': r.get('found_date', ''),
                    'm_fee': r.get('m_fee', ''),
                    't_fee': r.get('t_fee', ''),
                    'manager': r.get('manager', ''),
                    'manager_exp': r.get('manager_exp', ''),
                    'fund_type': r.get('fund_type', ''),
                }
        except Exception as e:
            print(f"查 fund_info 失败: {e}")

        # 2. 调 API
        info = await asyncio.to_thread(FundDataService.get_fund_info, code)
        if info and info.get('name'):
            try:
                await FundDataService.save_fund_info(code, info)
            except Exception as e:
                print(f"save_fund_info 失败: {e}")
        return info


# 全局服务实例
fund_data_service = FundDataService()
