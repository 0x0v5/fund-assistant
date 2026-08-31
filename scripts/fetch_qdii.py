#!/usr/bin/env python3
"""
QDII 场外基金额度检查脚本

两种调用方式：
1. CLI：`python scripts/fetch_qdii.py`
2. APScheduler in-process：`from scripts.fetch_qdii import run; await run()`

环境变量：
- FUND_API_BASE     后端 API 地址（默认 http://localhost:8000）
- QDII_CACHE_DIR    限额历史缓存目录（默认 ~/.cache/qdii，容器内建议指向持久卷）
"""

import httpx
import asyncio
import os
import sys
import json
from datetime import datetime
from pathlib import Path

from feishu_sender import send as send_feishu

# 选基助手 API 地址
API_BASE = os.environ.get("FUND_API_BASE", "http://localhost:8000")

# 缓存文件路径（容器内可通过 QDII_CACHE_DIR 覆盖）
CACHE_DIR = Path(os.environ.get("QDII_CACHE_DIR") or (Path.home() / ".hermes" / "cache"))
CACHE_FILE = CACHE_DIR / "qdii_quota_cache.json"


def simplify_name(name: str) -> str:
    """简化基金名称"""
    return (name
        .replace("(QDII)", "").replace("人民币", "")
        .replace("发起式联接", "联接").replace("发起联接", "联接")
        .replace("发起", "").replace("指数", ""))


def load_previous_cache() -> dict:
    """加载上次的限额数据"""
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"加载缓存失败: {e}")
    return {}


def save_cache(funds: list):
    """保存当前限额数据到缓存"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {
            f.get("code"): {
                "limit_amount": f.get("limit_amount", ""),
                "apply_status": f.get("apply_status", ""),
            }
            for f in funds
        }
        CACHE_FILE.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"保存缓存失败: {e}")


async def fetch_qdii_quota():
    """触发后端爬虫抓取 + 读取最新数据."""
    async with httpx.AsyncClient(timeout=180) as client:
        # 1. 触发爬虫并写入数据库
        refresh_resp = await client.post(f"{API_BASE}/api/qdii/quota/refresh")
        refresh_resp.raise_for_status()

        # 2. 从数据库读取（GET 不再触发爬虫）
        read_resp = await client.get(f"{API_BASE}/api/qdii/quota")
        read_resp.raise_for_status()
        return read_resp.json()


def format_message(data: dict, prev_cache: dict) -> str:
    """格式化飞书消息"""
    funds = data.get("funds", [])

    if not funds:
        return "📊 QDII 场外基金限额提醒\n\n暂无限额数据"

    update_time = data.get("update_time", "")[:19]

    # 按分类分组
    sp500_etf = [f for f in funds if f.get("type") == "ETF联接基金"]
    sp500_fof = [f for f in funds if f.get("type") == "FOF基金"]
    sp500_index = [f for f in funds if f.get("type") == "股票指数/LOF"]
    ndx_etf = [f for f in funds if f.get("type") == "纳指100 ETF联接"]
    ndx_direct = [f for f in funds if f.get("type") == "纳指100 直接指数"]

    messages = []

    # 标题
    messages.append("📊 QDII 场外基金限额提醒")
    messages.append(f"更新时间: {update_time}")
    messages.append("")

    # ========== 检测限额变化 ==========
    changed_funds = []
    for f in funds:
        code = f.get("code", "")
        prev = prev_cache.get(code, {})
        prev_limit = prev.get("limit_amount", "")
        curr_limit = f.get("limit_amount", "")

        # 跳过暂停申购的
        if f.get("apply_status") == "暂停申购":
            continue

        # 检测变化：有值且与上次不同
        if curr_limit and curr_limit != prev_limit:
            old_str = prev_limit if prev_limit else "无限额"
            changed_funds.append({
                "name": simplify_name(f.get("name", "")),
                "code": code,
                "old": old_str,
                "new": curr_limit,
            })

    if changed_funds:
        messages.append("🔔 限额变化:")
        for cf in changed_funds:
            messages.append(f"  {cf['code']} {cf['name']}: {cf['old']} → {cf['new']}元/天")
        messages.append("")

    # ========== 过滤条件：有具体限额金额 ==========
    def filter_with_limit(funds_list):
        return [
            f for f in funds_list
            if f.get("apply_status") != "暂停申购"
            and f.get("limit_amount", "")
            and f.get("limit_amount") not in ["", "无限额", "无"]
        ]

    sp500_funds = filter_with_limit(sp500_etf + sp500_fof + sp500_index)
    ndx_funds = filter_with_limit(ndx_etf + ndx_direct)

    # ========== 统计汇总 ==========
    sp500_total = sum(int(f.get("limit_amount", 0)) for f in sp500_funds if f.get("limit_amount", "").isdigit())
    ndx_total = sum(int(f.get("limit_amount", 0)) for f in ndx_funds if f.get("limit_amount", "").isdigit())

    messages.append("💰 每日限额汇总:")
    if sp500_total > 0:
        messages.append(f"  标普500: {sp500_total}元/天 ({len(sp500_funds)}只)")
    if ndx_total > 0:
        messages.append(f"  纳指100: {ndx_total}元/天 ({len(ndx_funds)}只)")
    if sp500_total == 0 and ndx_total == 0:
        messages.append("  暂无有效限额数据")
    messages.append("")

    # ========== 详细列表 ==========
    def format_fund(f):
        code = f.get("code", "")
        name = simplify_name(f.get("name", ""))
        limit = f.get("limit_amount", "")
        return f"  {code} {name}: {limit}元/天"

    sections = [
        ("标普500 ETF联接", filter_with_limit(sp500_etf)),
        ("标普500 FOF", filter_with_limit(sp500_fof)),
        ("标普500 指数", filter_with_limit(sp500_index)),
        ("纳指100 ETF联接", filter_with_limit(ndx_etf)),
        ("纳指100 直接指数", filter_with_limit(ndx_direct)),
    ]

    for title, fund_list in sections:
        if fund_list:
            messages.append(f"【{title}】")
            for f in fund_list:
                messages.append(format_fund(f))
            messages.append("")

    # 底部统计
    all_limited = sp500_funds + ndx_funds
    stopped = len([f for f in funds if f.get("apply_status") == "暂停申购"])
    messages.append(f"— 可买 {len(all_limited)} 只 | 暂停 {stopped} 只 —")

    return "\n".join(messages)


async def run() -> bool:
    """执行 QDII 限额检查全流程。

    Returns:
        True 成功（数据已抓取 + 飞书已推送），False 任一步骤失败
    """
    print(f"[{datetime.now().isoformat()}] 开始 QDII 场外基金限额检查...")

    try:
        # 加载上次缓存
        prev_cache = load_previous_cache()
        print(f"已加载 {len(prev_cache)} 只基金的历史限额数据")

        # 获取数据
        data = await fetch_qdii_quota()
        funds = data.get("funds", [])

        # 生成消息
        message = format_message(data, prev_cache)

        # 保存当前数据到缓存
        save_cache(funds)

        # 发送通知
        if not send_feishu(message):
            print("错误: 飞书推送彻底失败", file=sys.stderr)
            return False

        # 统计
        limited = len([f for f in funds if f.get("limit_amount", "") and f.get("apply_status") != "暂停申购"])
        stopped = len([f for f in funds if f.get("apply_status") == "暂停申购"])
        print(f"检查完成，可买 {limited} 只，暂停 {stopped} 只")
        return True

    except httpx.ConnectError:
        print("错误: 无法连接到选基助手 API，请确保后端服务正在运行")
        return False
    except Exception as e:
        print(f"错误: {e}")
        return False


async def main():
    """CLI 入口：调用 run() 并按结果退出。"""
    ok = await run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
