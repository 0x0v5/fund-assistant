"""飞书通知发送（scripts 共享）。

通过飞书开放平台 Open API 直接推送，需要企业自建应用凭据：
  - FEISHU_APP_ID      必填，飞书应用 App ID
  - FEISHU_APP_SECRET  必填，飞书应用 App Secret
  - FEISHU_CHAT_ID     必填，目标群 chat_id（oc_xxx），不受群改名影响

设计：
- 接口与旧版完全兼容：`send(message, target=None, max_retries=3) -> bool`
  上游 3 个 cron 脚本（fetch_qdii.py / run_momentum.py / industry_ranking.py）
  不用改一行代码。
- tenant_access_token 进程内缓存；剩余有效期 < 600 秒时主动刷新，避免边界过期。
- 失败重试 3 次（0s / 30s / 60s 退避），覆盖 token 过期 / 网络抖动场景。
- 彻底失败时返回 False，由调用方决定是否 sys.exit(1)。
- 注意：当前仅实现纯文本推送（msg_type=text）。如需图片 / 卡片，
  请用 `requests` 直接调 https://open.feishu.cn/open-apis/im/v1/images 等端点
  （msg_type=image 需要先 upload image_key，msg_type=interactive 需要 template_id）。
"""

import os
import sys
import time
from typing import Optional

import httpx

# Open API 端点（注意是 open-apis 复数，不是 open-api）
TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
SEND_URL = "https://open.feishu.cn/open-apis/message/v4/send"

# 重试配置
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (0, 30, 60)  # 第 1 次立刻试，失败等 30s 再试，失败等 60s 再试

# token 缓存（进程级单例）
_tenant_token: Optional[str] = None
_token_expire: float = 0.0


def _read_config() -> tuple[str, str, str]:
    """从环境变量读取 App ID / Secret / 默认 chat_id，缺任一就 raise。"""
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = os.environ.get("FEISHU_CHAT_ID", "")
    missing = [n for n, v in (
        ("FEISHU_APP_ID", app_id),
        ("FEISHU_APP_SECRET", app_secret),
        ("FEISHU_CHAT_ID", chat_id),
    ) if not v]
    if missing:
        raise RuntimeError(f"飞书推送配置缺失：{', '.join(missing)}")
    return app_id, app_secret, chat_id


def _get_tenant_access_token() -> str:
    """获取 tenant_access_token；剩余有效期 < 600 秒时主动刷新。"""
    global _tenant_token, _token_expire

    now = time.time()
    if _tenant_token and now < _token_expire - 600:
        return _tenant_token

    app_id, app_secret, _ = _read_config()
    resp = httpx.post(
        TOKEN_URL,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=TIMEOUT_SECONDS,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

    _tenant_token = data["tenant_access_token"]
    _token_expire = now + int(data.get("expire", 7200))
    return _tenant_token


def _send_once(message: str, chat_id: str) -> tuple[bool, str]:
    """单次发送尝试。返回 (success, error_msg)。

    成功响应：{"code": 0, "msg": "success", "data": {"message_id": "..."}}
    """
    try:
        token = _get_tenant_access_token()
    except Exception as e:
        return False, f"获取 token 失败: {e}"

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "chat_id": chat_id,
        "msg_type": "text",
        "content": {"text": message},
    }
    try:
        resp = httpx.post(SEND_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        if body.get("code") == 0:
            return True, ""
        err = body.get("msg") or body.get("message") or resp.text[:200]
        # 400 / 401 / token 失效类错误，强制刷新 token 后让上层重试
        if any(code in err for code in ("99991663", "99991668", "token")):
            global _tenant_token, _token_expire
            _tenant_token = None
            _token_expire = 0
        return False, err
    except httpx.TimeoutException:
        return False, f"timeout ({TIMEOUT_SECONDS}s)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send(message: str, target: Optional[str] = None, max_retries: int = MAX_RETRIES) -> bool:
    """通过飞书 Open API 发送文本消息（带重试）。

    Args:
        message: 消息正文
        target: 目标 chat_id；以 oc_ 开头时覆盖 FEISHU_CHAT_ID；
                其它值仅作日志标识（多群推送时方便区分）
        max_retries: 最多重试次数（不含首次）

    Returns:
        True 发送成功，False 失败
    """
    try:
        _, _, default_chat_id = _read_config()
    except RuntimeError as e:
        print(f"飞书推送跳过：{e}")
        return False

    # target 是 oc_xxx 形式时视为 chat_id 覆盖；否则仅作日志标识
    if target and target.startswith("oc_"):
        chat_id = target
        log_target = target
    else:
        chat_id = default_chat_id
        log_target = target or default_chat_id

    # 首次 + 最多 max_retries 次重试
    for attempt in range(max_retries + 1):
        if attempt > 0:
            backoff = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            print(f"第 {attempt}/{max_retries} 次重试（等待 {backoff}s）...")
            time.sleep(backoff)
        ok, err = _send_once(message, chat_id)
        if ok:
            print(f"飞书消息发送成功  (chat_id={log_target})")
            return True
        print(f"飞书消息发送失败: {err}")

    print(f"飞书消息彻底失败：已重试 {max_retries} 次")
    return False


def main():
    """CLI 入口：echo 读 stdin 发送（用于临时测试或管道调用）。

    用法: echo "hello" | python -m feishu_sender
    """
    message = sys.stdin.read().strip()
    if not message:
        print("用法: echo 'message' | python -m feishu_sender", file=sys.stderr)
        sys.exit(2)
    ok = send(message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()