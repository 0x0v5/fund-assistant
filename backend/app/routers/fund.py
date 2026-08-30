"""Fund evaluation API router.

架构（与 QDII/ETF/Industry 统一）：
- GET  /api/fund/eval/{code}            从 DB 读最新一次评测（不抓数据）
- POST /api/fund/eval/{code}/refresh    抓数据 + 写 DB（cron / 手动）
- POST /api/fund/eval/batch-refresh     批量刷新（cron 预拉用）
- GET  /api/fund/info/{code}            从 DB 读基本信息
- GET  /api/fund/history/{code}         从 DB 读历史净值
- GET  /api/fund/eval/history           评测历史
- GET  /api/fund/search                 基金搜索
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.models.schemas import FundEval, FundHistory, FundIndicator
from app.services.fund_eval import eval_service
from app.services.fund_data import fund_data_service
from app.db.database import execute_update, execute_query, execute_many

router = APIRouter()


# ============ 核心：刷新一支基金的评测 ============

def _is_etf_code(code: str) -> bool:
    """判断是否为场内 ETF（区别于普通基金 / LOF）。

    ETF 代码特征：
    - 159xxx：深交所 ETF
    - 5xxxxx：上交所 ETF（510-519、560-563、588-589 等）
    """
    return bool(code) and code.startswith(("159", "510", "511", "512", "513", "514",
                                           "515", "516", "517", "518", "519",
                                           "560", "561", "562", "563", "588", "589"))


async def refresh_fund_eval(code: str) -> dict:
    """抓一只基金的最新数据 + 写 DB + 返回评测结果。

    增量策略：DB 里最新一条 date 距今 ≤ 1 天就不重抓；
    否则只拉 days_lag + 1 天的数据。

    特别处理 ETF：
    - ETF 的净值应由 ETF 轮动/回测模块从新浪 K 线同步，并已做份额拆分复权；
    - 基金评测不再从东方财富覆盖 ETF 的 fund_nav，避免拆分数据被洗回原始价。
    """
    is_etf = _is_etf_code(code)

    # 1. 检查 DB 最新一条
    existing = await execute_query(
        "SELECT date FROM fund_nav WHERE code = ? ORDER BY date DESC LIMIT 1",
        (code,),
    )
    need_full_fetch = not existing

    if existing:
        try:
            last_date = datetime.strptime(existing[0]['date'], '%Y-%m-%d').date()
            days_lag = (datetime.now().date() - last_date).days
            if days_lag <= 0:
                # 已包含今天 → 直接用 DB 评测，不抓数据
                need_full_fetch = False
                fetch_days = 0
            else:
                fetch_days = days_lag + 1
        except Exception:
            fetch_days = 7
            need_full_fetch = False
    else:
        # 首次或失败重试：拉满 5 年以覆盖 3y / 5y 收益计算
        fetch_days = 1825

    # 2. 抓基本信息（异步）
    fund_info = await fund_data_service.get_fund_info_cached(code)
    if not fund_info.get('name'):
        # 缓存没命中，强制刷新一次
        fresh = await fund_data_service.get_fund_info_async(code)
        if fresh.get('name'):
            fund_info = fresh
            await fund_data_service.save_fund_info(code, fund_info)

    # 3. 抓增量净值
    # ETF 不走基金净值 API，直接用 DB 里的后复权 K 线数据
    if is_etf:
        nav_df = None
    elif need_full_fetch:
        nav_df = await fund_data_service.get_fund_nav_full_async(code)
    elif fetch_days > 0:
        nav_df = await fund_data_service.get_fund_nav_async(code, days=fetch_days)
    else:
        nav_df = None

    # 4. 合并数据
    import pandas as pd
    db_nav = await execute_query(
        "SELECT * FROM fund_nav WHERE code = ? ORDER BY date ASC", (code,)
    )
    if nav_df is not None and not nav_df.empty:
        api_nav = [{
            'code': code,
            'date': str(row['date'].date()),
            'nav': row['nav'],
            'accumulated_nav': row.get('accumulated_nav', row['nav']),
        } for _, row in nav_df.iterrows()]
        merged = {str(r['date']): r for r in db_nav}
        merged.update({n['date']: n for n in api_nav})
        all_nav_df = pd.DataFrame(list(merged.values()))
        if not all_nav_df.empty:
            all_nav_df['date'] = pd.to_datetime(all_nav_df['date'])
            all_nav_df = all_nav_df.sort_values('date').reset_index(drop=True)
    else:
        all_nav_df = pd.DataFrame(db_nav) if db_nav else pd.DataFrame()
        if not all_nav_df.empty:
            all_nav_df['date'] = pd.to_datetime(all_nav_df['date'])
            all_nav_df = all_nav_df.sort_values('date').reset_index(drop=True)

    if all_nav_df.empty or len(all_nav_df) < 30:
        raise HTTPException(status_code=404, detail="净值数据不足（<30 天）")

    # 5. 同类基金 1y 收益百分位
    peer_returns = await _get_peer_returns_1y(
        code, fund_info.get('fund_type', ''),
    )

    # 6. 计算评测
    result = eval_service.evaluate_fund_from_df(
        code, fund_info.get('name', ''), fund_info, all_nav_df,
        peer_returns=peer_returns,
    )

    if not result.get('name'):
        raise HTTPException(status_code=404, detail="基金不存在或获取数据失败")

    # 7. 写 DB
    eval_time = datetime.now().isoformat()
    await save_fund_eval(result, fund_info, eval_time)
    # ETF 的 fund_nav 由 ETF 模块维护，不覆盖
    if not is_etf:
        await save_nav_data(code, all_nav_df, eval_time)

    return {
        'result': result,
        'fund_info': fund_info,
        'fetch_days': fetch_days,
        'eval_time': eval_time,
        'nav_count': len(all_nav_df),
    }


async def _get_peer_returns_1y(code: str, fund_type: str) -> Optional[list]:
    """查同类基金近 1 年收益列表（用于百分位）。"""
    if not fund_type:
        return None
    try:
        # 从 fund_eval_history 拿同 fund_type 的最近一次 1y 收益
        rows = await execute_query("""
            SELECT DISTINCT code, return_1y FROM fund_eval_history
            WHERE fund_type = ? AND code != ? AND return_1y IS NOT NULL
            ORDER BY eval_time DESC
            LIMIT 200
        """, (fund_type, code))
        # 每个 code 取最新一条
        seen = set()
        returns = []
        for r in rows:
            c = r['code']
            if c in seen:
                continue
            seen.add(c)
            returns.append(r['return_1y'])
        return returns if returns else None
    except Exception as e:
        print(f"查同类基金失败: {e}")
        return None


# ============ API ============

# 注意：/eval/history 必须定义在 /eval/{fund_code} 之前，
# 否则 FastAPI 会把 "history" 当成 fund_code。

async def _get_fund_brief(code: str) -> dict:
    """获取自选基金列表展示用的粗略信息。"""
    try:
        info_rows = await execute_query("SELECT * FROM fund_info WHERE code = ?", (code,))
        info = dict(info_rows[0]) if info_rows else {}
        for k in ('name', 'scale', 'found_date', 'm_fee', 't_fee', 'manager', 'manager_exp', 'fund_type'):
            info.setdefault(k, '')

        eval_rows = await execute_query("""
            SELECT score, return_1y, eval_time FROM fund_eval_history
            WHERE code = ? ORDER BY eval_time DESC LIMIT 1
        """, (code,))
        eval_ = eval_rows[0] if eval_rows else {}

        return {
            'code': code,
            'name': info.get('name', code),
            'fund_type': info.get('fund_type', ''),
            'manager': info.get('manager', ''),
            'score': eval_.get('score'),
            'return_1y': eval_.get('return_1y'),
            'eval_time': eval_.get('eval_time', ''),
        }
    except Exception as e:
        print(f"获取基金 {code} 粗略信息失败: {e}")
        return {'code': code, 'name': code}


@router.get("/favorites")
async def get_favorite_funds():
    """获取用户自选基金列表（含粗略信息）。"""
    try:
        rows = await execute_query("SELECT code FROM user_favorite_funds ORDER BY created_at DESC")
        funds = []
        for r in rows:
            brief = await _get_fund_brief(r['code'])
            funds.append(brief)
        return {"data": funds}
    except Exception as e:
        print(f"获取自选基金失败: {e}")
        return {"data": []}


@router.post("/favorites/{code}")
async def add_favorite_fund(code: str):
    """添加自选基金。"""
    try:
        await execute_update("""
            INSERT INTO user_favorite_funds (code, created_at)
            VALUES (?, ?)
            ON CONFLICT(code) DO NOTHING
        """, (code, datetime.now().isoformat()))
        return {"message": "添加成功", "code": code}
    except Exception as e:
        print(f"添加自选基金失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/favorites/{code}")
async def remove_favorite_fund(code: str):
    """移除自选基金。"""
    try:
        await execute_update("DELETE FROM user_favorite_funds WHERE code = ?", (code,))
        return {"message": "移除成功", "code": code}
    except Exception as e:
        print(f"移除自选基金失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evaluated")
async def get_evaluated_funds():
    """获取所有已评测基金列表（含粗略信息）。"""
    try:
        rows = await execute_query("""
            SELECT DISTINCT code FROM fund_eval_history
            ORDER BY code
        """)
        funds = []
        for r in rows:
            brief = await _get_fund_brief(r['code'])
            funds.append(brief)
        return {"data": funds}
    except Exception as e:
        print(f"获取已评测基金失败: {e}")
        return {"data": []}


@router.get("/eval/history")
async def get_eval_history(code: str = None, days: int = 30):
    """获取基金评测历史记录"""
    try:
        if code:
            rows = await execute_query("""
                SELECT * FROM fund_eval_history
                WHERE code = ?
                ORDER BY eval_time DESC
                LIMIT ?
            """, (code, days))
        else:
            rows = await execute_query("""
                SELECT * FROM fund_eval_history
                ORDER BY eval_time DESC
                LIMIT ?
            """, (days,))
        return {"data": rows}
    except Exception as e:
        print(f"获取历史记录失败: {e}")
        return {"data": []}


@router.get("/eval/{fund_code}")
async def evaluate_fund(fund_code: str):
    """读 DB 最新评测（不再触发抓数据）。"""
    try:
        rows = await execute_query("""
            SELECT * FROM fund_eval_history
            WHERE code = ?
            ORDER BY eval_time DESC LIMIT 1
        """, (fund_code,))
        if not rows:
            raise HTTPException(status_code=404, detail="该基金尚未评测，请先点击「更新数据」")

        r = rows[0]

        # 读 fund_info
        info_rows = await execute_query("SELECT * FROM fund_info WHERE code = ?", (fund_code,))
        fund_info = dict(info_rows[0]) if info_rows else {'name': r.get('name', '')}
        # 兼容旧字段
        for k in ('name', 'scale', 'found_date', 'm_fee', 't_fee', 'manager', 'manager_exp', 'fund_type'):
            fund_info.setdefault(k, '')

        indicators = []
        for key, label in [
            ('return_1y', '近1年收益'), ('return_3y', '近3年收益'), ('return_5y', '近5年收益'),
        ]:
            indicators.append(_build_indicator_from_row(r, key, label, 'return'))
        for key, label in [
            ('sharpe', '夏普比率'), ('sortino', 'Sortino比率'), ('calmar', '卡玛比率'),
            ('max_drawdown', '最大回撤'), ('volatility', '年化波动'), ('profit_prob', '盈利概率'),
        ]:
            indicators.append(_build_indicator_from_row(r, key, label, 'risk'))
        if r.get('return_1y_pct') is not None:
            indicators.append({
                'name': '同类1y百分位',
                'value': r['return_1y_pct'],
                'score': int(r['return_1y_pct']),
                'type': 'rank',
                'note': f'高于{r["return_1y_pct"]:.0f}%同类基金',
            })

        # 雷达图
        radar_indicators = [
            {'name': '收益能力', 'value': _clamp(50 + (r.get('return_1y') or 0), 0, 100)},
            {'name': '稳定性', 'value': _clamp(100 - abs(r.get('max_drawdown') or 0), 0, 100)},
            {'name': '风险收益', 'value': _clamp((r.get('sharpe') or 0) * 30 + 50, 0, 100)},
            {'name': '盈利概率', 'value': _clamp(r.get('profit_prob') or 50, 0, 100)},
            {'name': '低波动', 'value': _clamp(100 - (r.get('volatility') or 0) * 2, 0, 100)},
        ]

        return FundEval(
            code=r['code'],
            name=r.get('name', ''),
            score=r.get('score', 0) or 0,
            indicators=[FundIndicator(**i) for i in indicators if i.get('value') is not None or i.get('note')],
            radar_data={'indicators': radar_indicators},
            info=fund_info,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"读评测失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _build_indicator_from_row(r: dict, key: str, label: str, type_: str) -> dict:
    """从 DB 行生成指标 dict。value 为 None 时返回带 note 的占位。"""
    v = r.get(key)
    if v is None:
        return {'name': label, 'value': None, 'score': 0, 'type': type_, 'note': '数据不足'}
    score = int(_clamp(v * 2 + 50 if type_ == 'return' else 50, 0, 100))
    if '回撤' in label or '波动' in label:
        score = int(_clamp(100 - abs(v) * (2 if '波动' in label else 1), 0, 100))
    elif '夏普' in label or 'Sortino' in label or '卡玛' in label:
        score = int(_clamp((v or 0) * 30 + 50, 0, 100))
    elif '概率' in label:
        score = int(_clamp(v, 0, 100))
    return {'name': label, 'value': v, 'score': score, 'type': type_}


@router.post("/eval/{fund_code}/refresh")
async def refresh_evaluate_fund(fund_code: str):
    """手动刷新一只基金的评测。"""
    try:
        out = await refresh_fund_eval(fund_code)
        return {
            'message': '刷新完成',
            'code': fund_code,
            'eval_time': out['eval_time'],
            'fetch_days': out['fetch_days'],
            'nav_count': out['nav_count'],
            'result': out['result'],
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"刷新评测失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/eval/batch-refresh")
async def batch_refresh_funds(codes: list[str] = None):
    """批量刷新。codes 为 None 时刷新最近 30 天查过的所有基金。"""
    if codes is None or len(codes) == 0:
        rows = await execute_query("""
            SELECT DISTINCT code FROM fund_eval_history
            WHERE eval_time >= datetime('now', '-30 days')
        """)
        codes = [r['code'] for r in rows]
    results = []
    for code in codes:
        try:
            out = await refresh_fund_eval(code)
            results.append({'code': code, 'status': 'ok', 'eval_time': out['eval_time']})
        except Exception as e:
            results.append({'code': code, 'status': 'error', 'error': str(e)})
    return {'message': f'刷新 {len(results)} 只', 'results': results}


async def save_fund_eval(result: dict, fund_info: dict, eval_time: str):
    """保存基金评测结果到数据库。"""
    try:
        indicators = {ind['name']: ind['value'] for ind in result.get('indicators', [])}
        fund_type = fund_info.get('fund_type', '')

        await execute_update("""
            INSERT INTO fund_eval_history
            (code, name, score, return_1y, return_3y, return_5y,
             sharpe, sortino, calmar, max_drawdown, volatility, profit_prob,
             return_1y_pct, pe, pb, roe, fund_type, eval_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.get('code', ''),
            result.get('name', ''),
            result.get('score', 0),
            indicators.get('近1年收益'),
            indicators.get('近3年收益'),
            indicators.get('近5年收益'),
            indicators.get('夏普比率'),
            indicators.get('Sortino比率'),
            indicators.get('卡玛比率'),
            indicators.get('最大回撤'),
            indicators.get('年化波动'),
            indicators.get('盈利概率'),
            indicators.get('同类1y百分位'),
            indicators.get('市盈率'),
            indicators.get('市净率'),
            indicators.get('ROE'),
            fund_type,
            eval_time,
        ))
    except Exception as e:
        print(f"保存评测数据失败: {e}")


async def save_nav_data(code: str, nav_df, eval_time: str):
    """保存净值数据到数据库。"""
    if nav_df is None or nav_df.empty:
        return
    try:
        import pandas as pd
        nav_records = []
        for _, row in nav_df.iterrows():
            date = str(row['date'].date()) if hasattr(row['date'], 'date') else row['date']
            # 跳过周末（基金/ETF 净值只应在交易日）
            try:
                dt = pd.to_datetime(date)
                if dt.weekday() >= 5:
                    continue
            except Exception:
                pass

            nav = float(row['nav'])
            accumulated = float(row.get('accumulated_nav') if pd.notna(row.get('accumulated_nav')) else row['nav'])

            # 校验：acc/nav 比例异常时回退到 nav
            if nav > 0 and (accumulated / nav > 1.5 or accumulated / nav < 0.8):
                print(f"[Fund {code}] {date} accumulated_nav 异常 ({accumulated:.4f}/{nav:.4f})，回退到 nav")
                accumulated = nav

            nav_records.append((code, date, nav, accumulated))

        if not nav_records:
            return

        await execute_many("""
            INSERT INTO fund_nav (code, date, nav, accumulated_nav)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code, date) DO UPDATE SET
                nav = excluded.nav,
                accumulated_nav = excluded.accumulated_nav
        """, nav_records)
    except Exception as e:
        print(f"保存净值数据失败: {e}")


@router.get("/history/{fund_code}")
async def get_fund_history(fund_code: str, period: str = "1y"):
    """获取基金历史净值数据。"""
    try:
        days_map = {"1y": 365, "3y": 1095, "5y": 1825, "10y": 3650}
        days = days_map.get(period, 365)

        db_data = await execute_query("""
            SELECT * FROM fund_nav
            WHERE code = ? AND date >= date('now', ?)
            ORDER BY date ASC
        """, (fund_code, f"-{days} days"))

        history = [
            FundHistory(
                code=row['code'],
                date=row['date'],
                nav=row['nav'],
                accumulated_nav=row.get('accumulated_nav', row['nav']),
            )
            for row in db_data
        ]
        return sorted(history, key=lambda x: x.date)

    except Exception as e:
        print(f"获取净值历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_funds(keyword: str):
    """搜索基金"""
    try:
        results = fund_data_service.search_funds(keyword)
        return {"data": results}
    except Exception as e:
        print(f"搜索基金失败: {e}")
        return {"data": []}


@router.get("/info/{fund_code}")
async def get_fund_info(fund_code: str):
    """获取基金基本信息（从 DB 缓存；缺失时拉一次 API）"""
    try:
        info = await fund_data_service.get_fund_info_cached(fund_code)
        if not info or not info.get('name'):
            raise HTTPException(status_code=404, detail="基金不存在")
        return info
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取基金信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))