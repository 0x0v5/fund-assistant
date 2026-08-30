"""Industry sector monitoring API router.

架构（与 QDII / ETF 保持一致）：
- POST /api/industry/ranking/refresh   实时调新浪/腾讯 → 写 DB（cron 调度 / 手动更新）
- GET  /api/industry/ranking           从 DB 读最新一帧
- GET  /api/industry/funds             从 DB 读最新一帧
- GET  /api/industry/list              静态配置
- GET  /api/industry/history           历史记录

数据源（双轨）：
1. 全行业指数（腾讯 qt.gtimg.cn）：30+ 个行业指数实时涨跌幅（主）
2. ETF 代理（新浪 hq.sinajs.cn）：45 个细分行业 ETF 涨跌幅（细分场景）
"""

from datetime import datetime
from typing import Optional
import asyncio
import re
import requests
from fastapi import APIRouter, HTTPException

from app.models.schemas import IndustryFund, IndustryFundsResponse
from app.db.database import execute_update, execute_query

router = APIRouter()

# ============================================================
# 数据源 1: 全行业指数（腾讯 qt.gtimg.cn，实时涨跌幅）
# ============================================================
# 来自 CSI 一级行业（10 个）+ 中证细分行业（13 个）+ 300 行业（5 个）+ 内地主题（10 个）
# 去重后约 30+ 个，覆盖能源/材料/工业/消费/医药/金融/科技/通信等全行业板块
_INDUSTRY_INDICES = [
    # 中证一级行业（10 个）— 最权威的全行业基准
    {"code": "sh000928", "name": "中证能源", "category": "中证一级"},
    {"code": "sh000929", "name": "中证材料", "category": "中证一级"},
    {"code": "sh000930", "name": "中证工业", "category": "中证一级"},
    {"code": "sh000931", "name": "中证可选消费", "category": "中证一级"},
    {"code": "sh000932", "name": "中证主要消费", "category": "中证一级"},
    {"code": "sh000933", "name": "中证医药", "category": "中证一级"},
    {"code": "sh000934", "name": "中证金融", "category": "中证一级"},
    {"code": "sh000935", "name": "中证信息", "category": "中证一级"},
    {"code": "sh000936", "name": "中证通信", "category": "中证一级"},
    {"code": "sh000937", "name": "中证公用", "category": "中证一级"},
    # 中证细分行业（13 个）— 提供更细分的板块
    {"code": "sh000805", "name": "A股资源", "category": "中证细分"},
    {"code": "sh000806", "name": "消费服务", "category": "中证细分"},
    {"code": "sh000807", "name": "食品饮料", "category": "中证细分"},
    {"code": "sh000808", "name": "医药生物", "category": "中证细分"},
    {"code": "sh000811", "name": "细分有色", "category": "中证细分"},
    {"code": "sh000812", "name": "细分机械", "category": "中证细分"},
    {"code": "sh000813", "name": "细分化工", "category": "中证细分"},
    {"code": "sh000814", "name": "细分医药", "category": "中证细分"},
    {"code": "sh000815", "name": "细分食品", "category": "中证细分"},
    {"code": "sh000819", "name": "有色金属", "category": "中证细分"},
    {"code": "sh000820", "name": "煤炭指数", "category": "中证细分"},
    # 300 行业（5 个）— 沪深 300 内行业分布
    {"code": "sh000908", "name": "300能源", "category": "300行业"},
    {"code": "sh000909", "name": "300材料", "category": "300行业"},
    {"code": "sh000910", "name": "300工业", "category": "300行业"},
    {"code": "sh000911", "name": "300可选", "category": "300行业"},
    {"code": "sh000912", "name": "300消费", "category": "300行业"},
    # 内地主题（10 个）— 主题行业
    {"code": "sh000941", "name": "新能源", "category": "内地主题"},
    {"code": "sh000942", "name": "内地消费", "category": "内地主题"},
    {"code": "sh000944", "name": "内地资源", "category": "内地主题"},
    {"code": "sh000945", "name": "内地运输", "category": "内地主题"},
    {"code": "sh000948", "name": "内地地产", "category": "内地主题"},
    {"code": "sh000949", "name": "中证农业", "category": "内地主题"},
]


# ============================================================
# 数据源 2: 细分行业 ETF 代理（场内 ETF，作为细分场景补充）
# ============================================================
_INDUSTRY_ETFS = {
    "半导体": [
        {"code": "512480", "name": "国泰CES半导体芯片ETF"},
        {"code": "159995", "name": "华夏国证半导体芯片ETF"},
    ],
    "新能源": [
        {"code": "515030", "name": "华夏中证新能源汽车ETF"},
    ],
    "光伏": [
        {"code": "159857", "name": "天弘中证光伏产业ETF"},
    ],
    "医疗": [
        {"code": "512010", "name": "易方达中证万得医药ETF"},
        {"code": "159992", "name": "银华中证创新药产业ETF"},
    ],
    "消费": [
        {"code": "159928", "name": "汇添富中证主要消费ETF"},
    ],
    "白酒": [
        {"code": "512690", "name": "鹏华中证酒ETF"},
    ],
    "家电": [
        {"code": "159996", "name": "国泰中证全指家电ETF"},
    ],
    "汽车": [
        {"code": "515250", "name": "富国中证智能汽车ETF"},
    ],
    "银行": [
        {"code": "512800", "name": "华宝中证银行ETF"},
    ],
    "证券": [
        {"code": "512880", "name": "国泰中证全指证券公司ETF"},
    ],
    "保险": [
        {"code": "167301", "name": "方正富邦中证保险主题ETF"},
    ],
    "军工": [
        {"code": "512660", "name": "华夏中证军工ETF"},
    ],
    "化工": [
        {"code": "516020", "name": "华宝中证细分化工产业ETF"},
    ],
    "钢铁": [
        {"code": "515210", "name": "国泰中证钢铁ETF"},
    ],
    "有色金属": [
        {"code": "512400", "name": "南方中证申万有色金属ETF"},
    ],
    "煤炭": [
        {"code": "515220", "name": "国泰中证煤炭ETF"},
    ],
    "房地产": [
        {"code": "512200", "name": "南方中证全指房地产ETF"},
    ],
    "计算机": [
        {"code": "512720", "name": "华宝中证计算机ETF"},
    ],
    "通信": [
        {"code": "515050", "name": "华夏中证5G通信ETF"},
    ],
    "传媒": [
        {"code": "159805", "name": "国联安中证传媒ETF"},
    ],
    "游戏": [
        {"code": "159869", "name": "华夏中证动漫游戏ETF"},
    ],
    "教育": [
        {"code": "513360", "name": "博时中证全球中国教育ETF"},
    ],
    "农业": [
        {"code": "159825", "name": "富国中证农业主题ETF"},
    ],
    "养殖": [
        {"code": "159865", "name": "国泰中证畜牧养殖ETF"},
    ],
    "物流": [
        {"code": "516910", "name": "富国中证现代物流ETF"},
    ],
    "基建": [
        {"code": "516970", "name": "广发中证基建工程ETF"},
    ],
    "电子": [
        {"code": "159997", "name": "天弘中证电子ETF"},
    ],
    "半导体设备": [
        {"code": "159558", "name": "国泰中证半导体设备ETF"},
    ],
    "消费电子": [
        {"code": "561600", "name": "华泰柏瑞中证消费电子ETF"},
    ],
    "人工智能": [
        {"code": "159819", "name": "鹏华中证人工智能ETF"},
    ],
    "数字基建": [
        {"code": "159723", "name": "汇添富中证数字基建ETF"},
    ],
    "机器人": [
        {"code": "562500", "name": "华夏中证机器人ETF"},
    ],
    "工业母机": [
        {"code": "159663", "name": "华夏中证机床ETF"},
    ],
    "锂电池": [
        {"code": "159840", "name": "建信中证电池主题ETF"},
    ],
    "储能": [
        {"code": "159327", "name": "鹏华国证储能产业ETF"},
    ],
    "新材料": [
        {"code": "159703", "name": "天弘中证新材料主题ETF"},
    ],
    "稀土": [
        {"code": "159713", "name": "嘉实中证稀土产业ETF"},
    ],
    "医疗器械": [
        {"code": "159883", "name": "永赢中证全指医疗器械ETF"},
    ],
    "医药商业": [
        {"code": "159700", "name": "华夏中证全指医药商业ETF"},
    ],
    "食品饮料": [
        {"code": "515170", "name": "华夏中证食品饮料ETF"},
    ],
    "纺织服饰": [
        {"code": "159731", "name": "华夏中证全指纺织服装ETF"},
    ],
    "影视": [
        {"code": "159855", "name": "国泰中证影视主题ETF"},
    ],
    "环保": [
        {"code": "159861", "name": "国泰中证环保产业ETF"},
    ],
    "电力": [
        {"code": "159611", "name": "华夏中证全指电力公用事业ETF"},
    ],
    "黄金": [
        {"code": "518880", "name": "华安黄金ETF"},
    ],
}


# ============================================================
# 抓取函数
# ============================================================

def get_index_change(code: str) -> dict:
    """通过腾讯 qt.gtimg.cn 批量获取行业指数实时涨跌幅.

    返回字段与 ETF 代理保持一致，便于上层聚合。
    字段格式：v_sh000928="1~中证能源~000928~3162.72~3053.66~3049.90~...~3.57~..."
    索引位置（split('~') 后从 0 开始）：
      [1]=名称 [3]=当前价 [30]=日期(20260706) [31]=涨跌额 [32]=涨跌幅%
    """
    url = f"https://qt.gtimg.cn/q={code}"
    try:
        resp = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }, timeout=10)
        resp.encoding = 'gbk'
        text = resp.text.strip()
        m = re.search(rf'v_{re.escape(code)}="([^"]*)"', text)
        if not m:
            return {"code": code, "close": 0, "change_pct": 0, "date": "", "error": "no_data"}
        fields = m.group(1).split('~')
        if len(fields) < 33:
            return {"code": code, "close": 0, "change_pct": 0, "date": "", "error": "incomplete"}
        name = fields[1]
        try:
            current = float(fields[3]) if fields[3] else 0
            change_pct = float(fields[32]) if fields[32] else 0
        except (ValueError, IndexError):
            return {"code": code, "close": 0, "change_pct": 0, "date": "", "error": "parse_error"}
        date_str = fields[30] if len(fields) > 30 else ""
        return {
            "code": code,
            "name": name,
            "close": current,
            "change_pct": change_pct,
            "date": date_str,
        }
    except Exception as e:
        return {"code": code, "close": 0, "change_pct": 0, "date": "", "error": str(e)}


def get_etf_change(code: str) -> dict:
    """获取单只 ETF 的涨跌幅数据.

    策略：优先用 hq.sinajs.cn 实时接口（不受 IP 封禁影响，且收盘后字段稳定）；
    实时拿不到时降级到新浪 K 线 API；K 线也失败时返回 0。
    """
    from app.services.crawler import FundDataService

    try:
        rt = FundDataService.get_etf_realtime(code)
        if rt and rt.get("current_price", 0) > 0 and rt.get("prev_close", 0) > 0:
            return {
                "code": code,
                "close": float(rt["current_price"]),
                "change_pct": float(rt["change_pct"]),
                "date": (rt.get("update_time", "") or "")[:10],
                "source": "realtime",
            }
    except Exception as e:
        print(f"[{code}] 实时接口失败: {e}")

    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }
    code_prefix = 'sz' if code.startswith(('15', '16', '18')) else 'sh'
    url = 'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    params = {
        'symbol': f'{code_prefix}{code}',
        'scale': '240',
        'ma': 'no',
        'datalen': '5'
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        text = resp.text.strip()
        if not text.startswith('['):
            return {"code": code, "change_pct": 0, "close": 0, "date": "", "error": "kline_blocked"}
        data = resp.json()
        if not data or len(data) < 2:
            return {"code": code, "change_pct": 0, "close": 0, "date": ""}

        latest_day = data[-1]['day']
        today = datetime.now().strftime('%Y-%m-%d')

        if latest_day < today:
            try:
                rt = FundDataService.get_etf_realtime(code)
                if rt and rt.get("current_price", 0) > 0:
                    prev_close = float(rt.get("prev_close", 0))
                    current = float(rt["current_price"])
                    if prev_close > 0:
                        pct = (current - prev_close) / prev_close * 100
                    else:
                        pct = 0
                    return {
                        "code": code,
                        "close": round(current, 4),
                        "change_pct": round(pct, 2),
                        "date": today,
                        "source": "kline+realtime",
                    }
            except Exception:
                pass
            return {
                "code": code,
                "close": float(data[-1]['close']),
                "change_pct": 0,
                "date": latest_day,
                "stale": True,
            }

        today_bar = data[-1]
        yesterday_bar = data[-2]
        close_t = float(today_bar['close'])
        close_y = float(yesterday_bar['close'])
        pct = (close_t - close_y) / close_y * 100 if close_y > 0 else 0
        return {
            "code": code,
            "close": close_t,
            "change_pct": round(pct, 2),
            "date": today_bar['day'],
            "source": "kline",
        }
    except Exception as e:
        return {"code": code, "change_pct": 0, "close": 0, "date": "", "error": str(e)}


def calc_industry_change(funds: list) -> float:
    """计算行业平均涨跌幅."""
    changes = [f.get("change_pct", 0) for f in funds if f.get("change_pct") is not None]
    if not changes:
        return 0
    return round(sum(changes) / len(changes), 2)


def get_signal(change_pct: float) -> str:
    """根据涨跌幅生成信号."""
    if change_pct > 2:
        return "强势"
    elif change_pct > 0:
        return "偏强"
    elif change_pct > -2:
        return "偏弱"
    else:
        return "弱势"


async def save_industry_fund(fund: dict, industry: str, update_time: str, data_source: str = "etf"):
    """保存单只行业 ETF 数据到 DB（按 (code, update_time) 保留历史）.

    data_source: 'index' (全行业指数) | 'etf' (ETF代理)
    """
    await execute_update("""
        INSERT OR REPLACE INTO industry_funds
        (code, name, industry, nav, ytd_return, update_time, data_source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        fund.get("code", ""),
        fund.get("name", ""),
        industry,
        fund.get("close", 0),
        fund.get("change_pct", 0),
        update_time,
        data_source,
    ))


# ============ 读取助手 ============

def _fund_row_to_ranking_item(row: dict) -> dict:
    """把 DB 行转成前端期望的 fund_change 结构。"""
    return {
        "code": row["code"],
        "name": row.get("name", ""),
        "industry": row.get("industry", ""),
        "close": row.get("nav", 0),
        "change_pct": row.get("ytd_return", 0),
        "date": (row.get("update_time") or "")[:10],
        "data_source": row.get("data_source") or "etf",
    }


async def _read_ranking_from_db() -> dict:
    """从 DB 读最新一帧（每个 code 取最新 update_time），组装排名结构。

    优先展示指数源（全行业），其次 ETF 代理（细分场景）。
    指数和 ETF 代理的行业名不冲突时，会同时出现在排名中。
    """
    rows = await execute_query("""
        SELECT code, name, industry, nav, ytd_return, update_time,
               COALESCE(data_source, 'etf') as data_source
        FROM industry_funds
        WHERE (code, update_time) IN (
            SELECT code, MAX(update_time) FROM industry_funds GROUP BY code
        )
    """)
    if not rows:
        return {"ranking": [], "update_time": ""}

    # 按 (industry, data_source) 聚合成 ranking
    by_industry: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        ind = r.get("industry", "")
        source = r.get("data_source", "etf")
        key = (ind, source)
        by_industry.setdefault(key, []).append(_fund_row_to_ranking_item(r))

    ranking = []
    for (ind_name, source), funds in by_industry.items():
        avg_change = calc_industry_change(funds)
        ranking.append({
            "industry": ind_name,
            "change_pct": avg_change,
            "signal": get_signal(avg_change),
            "funds": funds,
            "data_source": source,
        })

    ranking.sort(key=lambda x: x["change_pct"], reverse=True)

    update_time = max((r.get("update_time", "") for r in rows), default="")
    return {"ranking": ranking, "update_time": update_time}


# ============ API ============

@router.get("/list")
async def get_industry_list():
    """获取行业列表（指数 + ETF 代理）"""
    return {
        "indices": _INDUSTRY_INDICES,
        "etfs": [
            {"name": name, "funds": funds}
            for name, funds in _INDUSTRY_ETFS.items()
        ],
    }


@router.post("/ranking/refresh")
async def refresh_ranking():
    """实时抓行业指数 + ETF，写入 DB."""
    update_time = datetime.now().isoformat()
    count = 0
    failures: list[dict] = []

    # 1) 抓行业指数（主数据源）
    index_failures = 0
    for idx in _INDUSTRY_INDICES:
        try:
            change_data = await asyncio.to_thread(get_index_change, idx["code"])
            if change_data.get("error"):
                index_failures += 1
                failures.append({"industry": idx["name"], "code": idx["code"], "source": "index", "error": change_data["error"]})
                continue
            await save_industry_fund(change_data, idx["name"], update_time, data_source="index")
            count += 1
        except Exception as e:
            index_failures += 1
            failures.append({"industry": idx["name"], "code": idx["code"], "source": "index", "error": str(e)})

    # 2) 抓 ETF 代理（细分场景）
    etf_failures = 0
    for ind_name, funds in _INDUSTRY_ETFS.items():
        for fund in funds:
            try:
                change_data = await asyncio.to_thread(get_etf_change, fund["code"])
                fund_data = {
                    "code": fund["code"],
                    "name": fund["name"],
                    "close": change_data.get("close", 0),
                    "change_pct": change_data.get("change_pct", 0),
                    "date": change_data.get("date", ""),
                }
                if change_data.get("error") and fund_data["change_pct"] == 0:
                    etf_failures += 1
                    failures.append({"industry": ind_name, "code": fund["code"], "source": "etf", "error": change_data["error"]})
                    continue
                await save_industry_fund(fund_data, ind_name, update_time, data_source="etf")
                count += 1
            except Exception as e:
                etf_failures += 1
                failures.append({"industry": ind_name, "code": fund["code"], "source": "etf", "error": str(e)})

    if failures:
        print(f"行业刷新部分失败: {len(failures)}/{count + len(failures)} (指数失败={index_failures}, ETF失败={etf_failures})")
        for f in failures[:10]:
            print(f"  - [{f.get('source', '?')}] {f.get('industry', '?')} {f.get('code', '?')}: {f['error']}")

    return {
        "message": "刷新完成" if not failures else f"刷新完成，{len(failures)} 只失败（指数{index_failures}/ETF{etf_failures}）",
        "count": count,
        "failed": len(failures),
        "index_failed": index_failures,
        "etf_failed": etf_failures,
        "update_time": update_time,
        "failures": failures[:20],
    }


@router.get("/ranking")
async def get_industry_ranking():
    """获取行业涨跌幅排名（从数据库读取）。"""
    return await _read_ranking_from_db()


@router.get("/funds")
async def get_industry_funds(industry: Optional[str] = None):
    """获取指定行业的基金列表（从 DB 读取每个 code 最新一帧）。"""
    base_sql = """
        SELECT code, name, industry, nav, ytd_return, update_time,
               COALESCE(data_source, 'etf') as data_source
        FROM industry_funds
        WHERE (code, update_time) IN (
            SELECT code, MAX(update_time) FROM industry_funds GROUP BY code
        )
    """
    if industry and (industry in _INDUSTRY_ETFS or any(idx["name"] == industry for idx in _INDUSTRY_INDICES)):
        sql = base_sql + " AND industry = ?"
        params = (industry,)
    else:
        sql = base_sql
        params = ()

    rows = await execute_query(sql, params)

    industries_by_name: dict[str, list] = {}
    for r in rows:
        ind = r.get("industry", "")
        industries_by_name.setdefault(ind, []).append(IndustryFund(
            code=r["code"],
            name=r.get("name", ""),
            industry=ind,
            nav=r.get("nav", 0),
            ytd_return=r.get("ytd_return", 0),
            risk_level="中",
        ))

    industries = [{"name": name, "funds": funds}
                  for name, funds in industries_by_name.items()]

    latest_update = max((r.get("update_time", "") for r in rows), default="")
    return IndustryFundsResponse(
        industries=industries,
        update_time=latest_update or datetime.now(),
    )


@router.get("/history")
async def get_industry_history(code: Optional[str] = None, days: int = 30):
    """获取行业基金历史记录"""
    try:
        if code:
            rows = await execute_query("""
                SELECT * FROM industry_funds
                WHERE code = ? AND update_time >= date('now', ?)
                ORDER BY update_time DESC
            """, (code, f'-{days} days'))
        else:
            rows = await execute_query("""
                SELECT * FROM industry_funds
                WHERE update_time >= date('now', ?)
                ORDER BY update_time DESC
            """, (f'-{days} days',))
        return {"data": rows}
    except Exception as e:
        print(f"获取历史记录失败: {e}")
        return {"data": []}