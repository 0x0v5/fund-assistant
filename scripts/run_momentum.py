#!/usr/bin/env python3
"""
ETF 双动量轮动策略执行脚本

两种调用方式：
1. CLI：`python scripts/run_momentum.py`
2. APScheduler in-process：`from scripts.run_momentum import run; await run()`

环境变量：
- FUND_API_BASE  后端 API 地址（默认 http://localhost:8000）
- PREVIEW=1      只生成本地预览，不推送飞书

推送格式：纯文本（msg_type=text），风格对齐 fetch_qdii.py / industry_ranking.py。
"""

import httpx
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional

from feishu_sender import send as send_feishu

API_BASE = os.environ.get("FUND_API_BASE", "http://localhost:8000")

# 标的池从 API 动态加载；进程内缓存，每次 run() 刷新一次
_POOL_CACHE: dict[str, str] = {}


async def _refresh_pool_cache() -> None:
    """每次推送前重新拉一次池子，确保前端新增/删除生效。"""
    global _POOL_CACHE
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{API_BASE}/api/etf/pool")
            r.raise_for_status()
            _POOL_CACHE = {
                it["code"]: (it.get("short_name") or it.get("name", ""))[:3]
                for it in r.json().get("pool", [])
                if it.get("code") and int(it.get("is_active", 1)) == 1
            }
    except Exception as e:
        print(f"警告: 拉取 ETF 池子失败: {e}（沿用上次缓存）")


def short_name(code: str, fallback: str = "") -> str:
    return _POOL_CACHE.get(code, fallback[:3] if fallback else code[:3])


def _rank_by(candidates: list[dict], key: str) -> dict[str, int]:
    """按给定字段降序排，返回 {code: rank}。"""
    ordered = sorted(candidates, key=lambda x: float(x.get(key, 0)), reverse=True)
    return {it.get("code", ""): i + 1 for i, it in enumerate(ordered)}


async def fetch_all_strategies() -> tuple[dict, dict]:
    """刷新 DB 后，同时读两种策略的最新数据。"""
    async with httpx.AsyncClient(timeout=120) as client:
        await client.post(f"{API_BASE}/api/etf/momentum/refresh")
        agg = (await client.get(f"{API_BASE}/api/etf/momentum",
                                  params={"strategy": "aggressive"})).json()
        con = (await client.get(f"{API_BASE}/api/etf/momentum",
                                  params={"strategy": "conservative"})).json()
        return agg, con


def _build_rows(aggressive: dict, conservative: dict) -> list[dict]:
    """把两种策略的数据合并成一行/标的的统一视图，按夏普评分降序。"""
    agg_by = {c.get("code"): c for c in aggressive.get("candidates", [])}
    con_by = {c.get("code"): c for c in conservative.get("candidates", [])}

    rows = []
    for code in _POOL_CACHE.keys():
        a = agg_by.get(code)
        if not a:
            continue
        c = con_by.get(code, {})
        rows.append({
            "code": code,
            "name": short_name(code, a.get("name", "")),
            "short": float(a.get("short_momentum", 0)),
            "above_ma60": bool(a.get("above_ma60", False)),
            "daily": float(a.get("daily_change", 0)),
            "agg_score": float(a.get("combined_score", 0)),
            "con_score": float(c.get("combined_score", 0)),
            "consec": int(a.get("consecutive_rank1_days", 0)),
        })
    rows.sort(key=lambda r: r["con_score"], reverse=True)
    return rows


def format_message(aggressive: dict, conservative: dict, switch_hint: str = "") -> str:
    """生成纯文本消息（对齐 fetch_qdii.py / industry_ranking.py 风格）。

    移动端友好：每行两个指标（空格分隔），避免窄屏自动换行错位。

    第一名专属块额外展示「连续第 1 N 天」（核心策略信号：达 3 天才满仓）。

    颜色规则（中国股市惯例）：
      涨跌：🔴 正 / 🟢 负
      60 日线：🔴 上方 / 🟢 下方
    """
    update_time = aggressive.get("last_update") or conservative.get("last_update") or ""
    time_str = update_time[:19].replace("T", " ") if update_time else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = _build_rows(aggressive, conservative)
    top = rows[0] if rows else None

    lines = ["📈 ETF 双动量轮动"]
    lines.append(f"更新时间: {time_str}")
    lines.append("")

    def _block(r) -> list[str]:
        daily_icon = "🔴" if r["daily"] >= 0 else "🟢"
        short_icon = "🔴" if r["short"] >= 0 else "🟢"
        score_icon = "🔴" if r["con_score"] >= 0 else "🟢"
        above_icon = "🔴" if r["above_ma60"] else "🟢"
        above_label = "60日线上" if r["above_ma60"] else "60日线下"
        return [
            f"今日 {daily_icon}{r['daily']:+.2f}%   短期 {short_icon}{r['short']:+.2f}%",
            f"{above_icon}{above_label}   评分 {score_icon}{r['con_score']:+.2f}",
        ]

    if top:
        lines.append(f"🥇 第一名：{top['name']}")
        lines.extend(_block(top))
        # 「连续第 1」专属块：达 3 天 🟢 已满仓信号；1-2 天 🟡 观察中
        consec_days = int(top.get("consec", 0))
        if consec_days >= 3:
            lines.append(f"🟢 连续第1: {consec_days} 天（已达 3 天门槛，满仓信号）")
        elif consec_days >= 1:
            lines.append(f"🟡 连续第1: {consec_days} 天（未达 3 天门槛，继续观察）")
        lines.append("")

    lines.append("【完整排名】按夏普评分")
    for i, r in enumerate(rows, 1):
        score_icon = "🔴" if r["con_score"] >= 0 else "🟢"
        consec_days = int(r.get("consec", 0))
        consec_str = f"   连1:{consec_days}天" if consec_days > 0 else ""
        lines.append(f"{score_icon} {i}. {r['name']} ({r['code']}){consec_str}")
        lines.extend(_block(r))
        lines.append("")

    if switch_hint:
        lines.append(f"💡 切换建议: {switch_hint}")

    # 去掉末尾连续空行
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


async def run(preview_only: Optional[bool] = None) -> bool:
    """执行 ETF 双动量计算 + 飞书纯文本推送全流程。

    Args:
        preview_only: True 只打印不推送；None 时从环境变量 PREVIEW 读取

    Returns:
        True 流程完成；False 抓取/推送失败
    """
    if preview_only is None:
        preview_only = os.environ.get("PREVIEW", "").lower() in ("1", "true", "yes")

    print(f"[{datetime.now().isoformat()}] 开始 ETF 动量计算...")

    try:
        # 先拉池子（前端新增/删除立即生效；失败时沿用上次缓存）
        await _refresh_pool_cache()
        if not _POOL_CACHE:
            print("警告: ETF 池子为空，跳过本次推送", file=sys.stderr)
            return False

        aggressive, conservative = await fetch_all_strategies()
        switch_hint = aggressive.get("switch_suggestion") or conservative.get("switch_suggestion") or ""
        message = format_message(aggressive, conservative, switch_hint)

        if preview_only:
            print()
            print("=" * 50)
            print("📋 PREVIEW ONLY (PREVIEW=1，未推送飞书)")
            print("=" * 50)
            print(message)
            print("=" * 50)
            return True

        if not send_feishu(message):
            print("错误: 飞书推送彻底失败", file=sys.stderr)
            return False

        print("计算完成，双策略数据已推送")
        return True

    except httpx.ConnectError:
        print("错误: 无法连接到选基助手 API", file=sys.stderr)
        return False
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return False


async def main():
    """CLI 入口：调用 run() 并按结果退出。"""
    ok = await run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())