"""跨模块"最近操作"聚合端点。

数据流：读 DB 中各模块的关键时间字段，UNION 后按时间倒序合并。
不回外部 API，只做廉价 DB 聚合。
"""

from datetime import datetime
from fastapi import APIRouter, Query

from app.db.database import execute_query

router = APIRouter()


@router.get("/recent")
async def recent_activity(limit: int = Query(10, ge=1, le=50)):
    """返回最近 N 条活动（评测、回测、cron 刷新等）。

    每条活动统一字段：
        kind       'fund_eval' | 'backtest_run' | 'etf_refresh' | 'qdii_refresh' | 'industry_refresh'
        title      简短标题（带图标符号前缀）
        summary    摘要文本（如收益、评分、ETF 排名）
        time       ISO 字符串
        link       前端路由
    """
    items: list[dict] = []

    # 1. 基金评测历史（最新 limit 条）
    eval_rows = await execute_query("""
        SELECT code, name, score, return_1y,
               substr(eval_time, 1, 16) AS eval_time_short
        FROM fund_eval_history
        WHERE id IN (
            SELECT MAX(id) FROM fund_eval_history GROUP BY code
        )
        ORDER BY eval_time DESC
        LIMIT ?
    """, (limit,))
    for r in eval_rows:
        score = r.get("score") or 0
        ret1y = r.get("return_1y")
        ret_str = ""
        if ret1y is not None:
            ret_str = f"  ·  1y {ret1y:+.1f}%"
        summary = f"综合评分 {score}{ret_str}"
        items.append({
            "kind": "fund_eval",
            "title": f"📊 基金评测  {r.get('name') or r['code']}",
            "summary": summary,
            "time": r["eval_time_short"] or "",
            "link": f"/fund-eval?code={r['code']}",
            "sort_ts": r["eval_time_short"] or "",
        })

    # 2. 回测记录（最新 limit 条）
    bt_rows = await execute_query("""
        SELECT id, name, strategy_type, total_return, created_at
        FROM backtest_runs
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    for r in bt_rows:
        tr = r.get("total_return")
        tr_str = f"  ·  收益 {tr:+.2f}%" if tr is not None else ""
        items.append({
            "kind": "backtest_run",
            "title": f"📈 回测完成  {r.get('name') or '回测 #' + str(r['id'])}",
            "summary": f"策略 {r['strategy_type']}{tr_str}",
            "time": (r.get("created_at") or "")[:16].replace("T", " "),
            "link": "/backtest",
            "sort_ts": r.get("created_at") or "",
        })

    # 3. ETF 动量最近一次刷新（cron 14:30 / 11:30 触发）
    etf_rows = await execute_query("""
        SELECT calc_time, COUNT(DISTINCT code) AS cnt
        FROM momentum_history
        WHERE calc_time = (SELECT MAX(calc_time) FROM momentum_history)
    """)
    if etf_rows:
        r = etf_rows[0]
        ts = (r.get("calc_time") or "")
        items.append({
            "kind": "etf_refresh",
            "title": "🔄 ETF 双动量已刷新",
            "summary": f"覆盖 {r.get('cnt') or 0} 只标的",
            "time": ts[:16].replace("T", " "),
            "link": "/etf-momentum",
            "sort_ts": ts,
        })

    # 4. QDII 额度最近一次刷新
    qdii_rows = await execute_query("""
        SELECT update_time, COUNT(DISTINCT code) AS cnt
        FROM qdii_quota
        WHERE update_time = (SELECT MAX(update_time) FROM qdii_quota)
    """)
    if qdii_rows:
        r = qdii_rows[0]
        ts = (r.get("update_time") or "")
        items.append({
            "kind": "qdii_refresh",
            "title": "🔄 QDII 额度已检查",
            "summary": f"扫描 {r.get('cnt') or 0} 只基金",
            "time": ts[:16].replace("T", " "),
            "link": "/qdii",
            "sort_ts": ts,
        })

    # 5. 行业最近一次刷新
    ind_rows = await execute_query("""
        SELECT update_time, COUNT(DISTINCT industry) AS cnt
        FROM industry_funds
        WHERE update_time = (SELECT MAX(update_time) FROM industry_funds)
    """)
    if ind_rows:
        r = ind_rows[0]
        ts = (r.get("update_time") or "")
        items.append({
            "kind": "industry_refresh",
            "title": "🔄 行业排名已更新",
            "summary": f"覆盖 {r.get('cnt') or 0} 个板块",
            "time": ts[:16].replace("T", " "),
            "link": "/industry",
            "sort_ts": ts,
        })

    # 排序：按 sort_ts（ISO 字符串可直接字典序倒序），截取 limit
    items.sort(key=lambda x: x.get("sort_ts") or "", reverse=True)
    items = items[:limit]

    # 把内部 sort_ts 字段移除，避免泄漏
    for it in items:
        it.pop("sort_ts", None)

    return {"items": items}
