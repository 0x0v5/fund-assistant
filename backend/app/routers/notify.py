"""飞书通知测试 API.

提供手动推送端点，便于在浏览器 / curl 中验证 Open API 配置是否正确。
所有推送走 `scripts/feishu_sender.send`，与 cron 任务共用同一条推送链路。

需要 backend 进程环境变量里注入：
  - FEISHU_APP_ID
  - FEISHU_APP_SECRET
  - FEISHU_CHAT_ID
"""

import os
import sys
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 让 scripts/feishu_sender.py 可被 import
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from feishu_sender import send as feishu_send  # noqa: E402

router = APIRouter()


class FeishuSendRequest(BaseModel):
    """推送请求体。"""
    message: str
    target: Optional[str] = None  # oc_xxx 时覆盖默认 chat_id；其它值仅日志标识


class FeishuSendResponse(BaseModel):
    """推送结果。"""
    success: bool
    app_configured: bool
    chat_id_preview: Optional[str] = None  # 仅显示前 8 字符，避免泄漏完整 chat_id
    target: Optional[str] = None
    timestamp: str
    error: Optional[str] = None


def _check_config() -> tuple[bool, Optional[str]]:
    """检查 3 个必需环境变量是否齐全，返回 (configured, chat_id_preview)。"""
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_CHAT_ID", "")
    ok = bool(app_id and app_secret and chat_id)
    preview = (chat_id[:8] + "...") if chat_id else None
    return ok, preview


def _missing_env_names() -> list[str]:
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_CHAT_ID", "")
    return [n for n, v in (
        ("FEISHU_APP_ID", app_id),
        ("FEISHU_APP_SECRET", app_secret),
        ("FEISHU_CHAT_ID", chat_id),
    ) if not v]


@router.get("/status")
async def notify_status():
    """查看当前飞书推送配置状态（用于排查凭据是否注入环境变量）。

    注意：出于安全考虑，App Secret 永不出现在响应中。
    """
    configured, preview = _check_config()
    return {
        "app_configured": configured,
        "chat_id_preview": preview,
        "app_id_set": bool(os.environ.get("FEISHU_APP_ID")),
        "app_secret_set": bool(os.environ.get("FEISHU_APP_SECRET")),
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/test")
async def notify_test():
    """发送一条固定的测试消息，用于验证推送链路。

    返回实际推送结果（成功/失败），不会因为失败而返回 5xx，
    因为排查时也想看到失败的错误信息。
    """
    missing = _missing_env_names()
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"飞书凭据未配置：{', '.join(missing)}；请在 backend 进程环境变量里注入",
        )

    message = (
        "🧪 选基助手推送测试\n"
        f"⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "如果你看到这条消息，说明 Open API 凭据（APP_ID / APP_SECRET / CHAT_ID）配置正确。"
    )

    configured, preview = _check_config()
    target = os.environ.get("FEISHU_CHAT_ID", "default")
    # feishu_send 是同步阻塞（最多 90s），放到线程池避免阻塞事件循环
    success = await asyncio.to_thread(feishu_send, message, target)

    return FeishuSendResponse(
        success=success,
        app_configured=True,
        chat_id_preview=preview,
        target=target,
        timestamp=datetime.now().isoformat(),
        error=None if success else "推送失败，查看后端日志获取详情",
    )


@router.post("/send")
async def notify_send(req: FeishuSendRequest):
    """发送自定义消息，用于手动推送任意内容。

    target 字段若以 `oc_` 开头会覆盖默认 chat_id 推送到其他群；
    其它值仅作为日志标识。
    """
    missing = _missing_env_names()
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"飞书凭据未配置：{', '.join(missing)}",
        )
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    configured, preview = _check_config()
    success = await asyncio.to_thread(feishu_send, req.message, req.target)

    return FeishuSendResponse(
        success=success,
        app_configured=True,
        chat_id_preview=preview,
        target=req.target or os.environ.get("FEISHU_CHAT_ID", "default"),
        timestamp=datetime.now().isoformat(),
        error=None if success else "推送失败，查看后端日志获取详情",
    )