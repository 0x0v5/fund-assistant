#!/usr/bin/env python3
"""
ETF 双动量轮动策略执行脚本

两种调用方式：
1. CLI（兼容 hermes cron）：`python scripts/run_momentum.py`
2. APScheduler in-process：`from scripts.run_momentum import run; await run()`

环境变量：
- FUND_API_BASE  后端 API 地址（默认 http://localhost:8000）
- PREVIEW=1      只生成本地预览，不推送飞书
- SKIP_CHART=1   跳过图片生成（飞书无图权限时回退纯文本）
"""

import httpx
import asyncio
import os
import sys
import tempfile
from datetime import datetime
from typing import Optional

from feishu_sender import send as send_feishu

API_BASE = os.environ.get("FUND_API_BASE", "http://localhost:8000")

# 标的短名映射（≤3 字）
SHORT_NAME = {
    "159915": "创业",
    "512890": "红利",
    "159941": "纳指",
    "518880": "黄金",
}
ALL_CODES = list(SHORT_NAME.keys())

# 中国股市惯例颜色
RED = "#f56c6c"    # 正数红
GREEN = "#67c23a"  # 负数绿
YELLOW = "#e6a23c"
GRAY = "#909399"
TEXT = "#303133"
BG_HEADER = "#fafafa"
BG_ROW_ALT = "#f8f9fa"

# matplotlib 配置
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ZH_FONT_CANDIDATES = ["PingFang SC", "Heiti SC", "STHeiti", "Hiragino Sans GB", "Microsoft YaHei"]
_AVAILABLE_FONTS = {f.name for f in font_manager.fontManager.ttflist}
for _name in ZH_FONT_CANDIDATES:
    if _name in _AVAILABLE_FONTS:
        plt.rcParams["font.sans-serif"] = [_name, "DejaVu Sans"]
        break
plt.rcParams["axes.unicode_minus"] = False

def _colored(value: float, fmt: str = "+.2f") -> str:
    """按中国股市惯例：正数红 / 负数绿，返回带 emoji 前缀的字符串。"""
    icon = "🔴" if value >= 0 else "🟢"
    return f"{icon}{value:{fmt}}"


def _sign_colored(value: float) -> str:
    """只显示正负号 + 颜色（用于动量2）。"""
    icon = "🔴" if value >= 0 else "🟢"
    return f"{icon}+" if value >= 0 else f"{icon}-"


SIG_EMOJI = {"buy": "🟢", "hold": "🟡", "sell": "🔴"}
SIG_TEXT = {"buy": "买入", "hold": "持有", "sell": "卖出"}


def short_name(code: str, fallback: str = "") -> str:
    return SHORT_NAME.get(code, fallback[:3] if fallback else code[:3])


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
    """把两种策略的数据合并成一行/标的的统一视图，按激进评分降序。"""
    agg_by = {c.get("code"): c for c in aggressive.get("candidates", [])}
    con_by = {c.get("code"): c for c in conservative.get("candidates", [])}
    agg_rank = _rank_by(aggressive.get("candidates", []), "combined_score")
    con_rank = _rank_by(conservative.get("candidates", []), "combined_score")

    rows = []
    for code in ALL_CODES:
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
            "signal": a.get("signal", "hold"),
            "agg_rank": agg_rank.get(code, "-"),
            "con_rank": con_rank.get(code, "-"),
        })
    rows.sort(key=lambda r: r["con_score"], reverse=True)
    return rows


def format_message(aggressive: dict, conservative: dict, switch_suggestion: str = "") -> str:
    """生成简明文案：仅第一名（夏普评分第一名）+ 切换提示。完整 4 行由图片表格承载。"""
    now = datetime.now()
    update_time = aggressive.get("last_update") or conservative.get("last_update") or ""
    time_str = update_time[:16].replace("T", " ") if update_time else now.strftime("%Y-%m-%d %H:%M")

    rows = _build_rows(aggressive, conservative)
    # 第一名 = 夏普评分第一名（表格也已按 con_score 排序）
    top = rows[0] if rows else None

    lines = [
        "📈 ETF 双动量轮动",
        f"⏱️ {time_str}",
        "",
    ]

    if top:
        sig_label = SIG_TEXT.get(top["signal"], "?")
        sig_emoji = SIG_EMOJI.get(top["signal"], "")
        lines.append(
            f"🥇 第一名: {top['name']} "
            f"{_colored(top['con_score'], '+.2f')} "
            f"{sig_emoji}{sig_label}"
        )

    if switch_suggestion:
        lines.append("")
        lines.append(switch_suggestion)

    return "\n".join(lines)


def render_table_image(rows: list[dict], update_time: str) -> str:
    """生成红绿着色表格图片，对齐前端 EtfMomentum.vue 列定义：
    标的 / 今日涨跌 / 短期(20日) / 60日线上方 / 综合评分 / 信号

    60 日线上方字段直接取自 API 的 `above_ma60` 布尔值，
    与前端页面展示一致（true=在 60 日线上方 / false=在 60 日线下方）。
    """
    # 列定义：(header, width, builder_func)
    # builder_func(r) -> (text, color, fontweight)
    def col_name(r):
        return (r["name"], TEXT, "bold")

    def col_today(r):
        v = r["daily"]
        return (f"{v:+.2f}%", RED if v >= 0 else GREEN, "normal")

    def col_short(r):
        # 短期 20 日涨幅（对齐前端 short_momentum）
        v = r["short"]
        return (f"{v:+.1f}%", RED if v >= 0 else GREEN, "normal")

    def col_above_ma60(r):
        # 60 日线上方（对齐前端 above_ma60，不再使用 medium_momentum 二值化）
        above = bool(r["above_ma60"])
        text = "true" if above else "false"
        return (text, GREEN if above else RED, "bold")

    def col_sharpe(r):
        v = r["con_score"]
        return (f"{v:+.2f}", RED if v >= 0 else GREEN, "normal")

    def col_signal(r):
        s = r["signal"]
        color = {"buy": GREEN, "hold": YELLOW, "sell": RED}.get(s, GRAY)
        return ({"buy": "买入", "hold": "持有", "sell": "卖出"}.get(s, s), color, "bold")

    columns = [
        ("标的", 1.0, col_name),
        ("今日涨跌", 1.1, col_today),
        ("短期(20日)", 1.3, col_short),
        ("60日线上方", 1.4, col_above_ma60),
        ("综合评分", 1.1, col_sharpe),
        ("信号", 1.0, col_signal),
    ]

    n_rows = len(rows) + 1  # +1 header
    n_cols = len(columns)
    col_widths = [c[1] for c in columns]
    total_w = sum(col_widths)

    cell_h = 1.0
    fig_w = total_w * 1.2
    fig_h = n_rows * cell_h + 0.6
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=140)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, total_w)
    ax.set_ylim(0, n_rows * cell_h)
    ax.axis("off")

    for i in range(n_rows):
        x_left = 0
        for j, w in enumerate(col_widths):
            if i == 0:
                bg = BG_HEADER
            elif i % 2 == 1:
                bg = "white"
            else:
                bg = BG_ROW_ALT
            ax.add_patch(plt.Rectangle(
                (x_left, (n_rows - 1 - i) * cell_h), w, cell_h,
                facecolor=bg, edgecolor="#e4e7ed", linewidth=0.7, zorder=0,
            ))
            x_left += w

    time_str = (update_time or datetime.now().isoformat())[:16].replace("T", " ")
    ax.text(total_w / 2, n_rows * cell_h + 0.25,
             f"ETF 双动量轮动（按夏普评分排序）   {time_str}",
             ha="center", va="center", fontsize=13, fontweight="bold", color=TEXT)

    x_left = 0
    for j, (header, w, _) in enumerate(columns):
        cx = x_left + w / 2
        cy = (n_rows - 1) * cell_h + cell_h / 2
        ax.text(cx, cy, header, ha="center", va="center",
                 fontsize=11, fontweight="bold", color=TEXT)
        x_left += w

    for i, r in enumerate(rows):
        x_left = 0
        for j, (_, w, builder) in enumerate(columns):
            text, color, weight = builder(r)
            cx = x_left + w / 2
            cy = (n_rows - 2 - i) * cell_h + cell_h / 2
            ax.text(cx, cy, text, ha="center", va="center",
                     fontsize=12, color=color, fontweight=weight)
            x_left += w

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    fd, path = tempfile.mkstemp(prefix="etf_table_", suffix=".png")
    os.close(fd)
    plt.savefig(path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


async def run(preview_only: Optional[bool] = None, skip_chart: Optional[bool] = None) -> bool:
    """执行 ETF 双动量计算 + 飞书推送全流程。

    Args:
        preview_only: True 只打印不推送；None 时从环境变量 PREVIEW 读取
        skip_chart: True 跳过表格图片生成；None 时从环境变量 SKIP_CHART 读取

    Returns:
        True 流程完成（含 preview 模式）；False 抓取/推送失败
    """
    if preview_only is None:
        preview_only = os.environ.get("PREVIEW", "").lower() in ("1", "true", "yes")
    if skip_chart is None:
        skip_chart = os.environ.get("SKIP_CHART", "").lower() in ("1", "true", "yes")

    print(f"[{datetime.now().isoformat()}] 开始 ETF 动量计算...")

    chart_path = ""
    try:
        aggressive, conservative = await fetch_all_strategies()
        rows = _build_rows(aggressive, conservative)
        update_time = aggressive.get("last_update") or conservative.get("last_update") or ""
        switch_hint = aggressive.get("switch_suggestion") or conservative.get("switch_suggestion") or ""
        message = format_message(aggressive, conservative, switch_hint)

        if skip_chart:
            print("已设置 SKIP_CHART=1，跳过图片生成")
        else:
            try:
                chart_path = render_table_image(rows, update_time)
                print(f"表格图片已生成: {chart_path}")
            except Exception as e:
                print(f"图片生成失败（不影响文本推送）: {e}")

        if chart_path and os.path.exists(chart_path):
            message = f"{message}\n\nMEDIA:{chart_path}"

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
    finally:
        # 预览模式保留图片；推送后清理
        if not preview_only and chart_path and os.path.exists(chart_path):
            try:
                os.remove(chart_path)
            except Exception:
                pass


async def main():
    """CLI 入口：调用 run() 并按结果退出。"""
    ok = await run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())