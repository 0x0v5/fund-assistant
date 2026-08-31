#!/usr/bin/env python3
"""
行业板块涨跌幅排名推送脚本

两种调用方式：
1. CLI：`python scripts/industry_ranking.py`
2. APScheduler in-process：`from scripts.industry_ranking import run; await run()`

环境变量：
- FUND_API_BASE  后端 API 地址（默认 http://localhost:8000）
"""

import httpx
import asyncio
import os
import sys
from datetime import datetime

from feishu_sender import send as send_feishu

# 选基助手 API 地址
API_BASE = os.environ.get("FUND_API_BASE", "http://localhost:8000")


async def fetch_industry_ranking():
    """触发后端实时抓取 + 读取最新数据。"""
    async with httpx.AsyncClient(timeout=120) as client:
        # 1. 触发后端实时调新浪并写入数据库
        refresh_resp = await client.post(f"{API_BASE}/api/industry/ranking/refresh")
        refresh_resp.raise_for_status()

        # 2. 从数据库读取（GET 不再触发实时抓取）
        read_resp = await client.get(f"{API_BASE}/api/industry/ranking")
        read_resp.raise_for_status()
        return read_resp.json()


def format_ranking_message(data: dict) -> str:
    """格式化行业排名消息."""
    ranking = data.get("ranking", [])

    if not ranking:
        return "📊 行业板块涨跌榜\n\n暂无数据"

    update_time = data.get("update_time", "")[:19]

    messages = ["📊 行业板块涨跌榜"]
    messages.append(f"更新时间: {update_time}")
    messages.append("")
    messages.append("【强势板块】")
    # 显示涨幅前3
    for item in ranking[:3]:
        pct = item.get("change_pct", 0)
        if pct > 0:
            messages.append(f"🔴 {item.get('industry', '')}: {pct:+.2f}%")

    messages.append("")
    messages.append("【弱势板块】")
    # 显示跌幅前3
    for item in ranking[-3:]:
        pct = item.get("change_pct", 0)
        if pct < 0:
            messages.append(f"🟢 {item.get('industry', '')}: {pct:+.2f}%")

    messages.append("")
    messages.append("【完整排名】")
    for i, item in enumerate(ranking, 1):
        pct = item.get("change_pct", 0)
        emoji = "🔴" if pct > 0 else ("🟢" if pct < 0 else "⚪")
        messages.append(f"{emoji} {i:2d}. {item.get('industry', '')}: {pct:+.2f}%")

    return "\n".join(messages)


async def run() -> bool:
    """执行行业涨跌榜抓取 + 推送全流程。

    Returns:
        True 成功（数据已抓取 + 飞书已推送），False 任一步骤失败
    """
    print(f"[{datetime.now().isoformat()}] 开始获取行业涨跌榜...")

    try:
        data = await fetch_industry_ranking()
        message = format_ranking_message(data)
        if not send_feishu(message):
            print("错误: 飞书推送彻底失败", file=sys.stderr)
            return False

        ranking = data.get("ranking", [])
        print(f"获取完成，共 {len(ranking)} 个行业")
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
