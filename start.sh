#!/bin/bash
# 选基助手 一键启动 / 重启脚本
#
# 用法:
#   ./start.sh start          启动后端 + 前端（已运行则跳过）
#   ./start.sh stop           停止后端 + 前端
#   ./start.sh restart        停止后启动
#   ./start.sh status         查看运行状态
#   ./start.sh logs [BACK|FRONT]  跟踪日志（不加参数看两个）
#   ./start.sh backend        只启动 / 重启后端
#   ./start.sh frontend       只启动 / 重启前端
#
# 配置（可通过环境变量覆盖）:
#   BACK_HOST=0.0.0.0  BACK_PORT=8000
#   FRONT_HOST=0.0.0.0 FRONT_PORT=5173
#   LOG_DIR=/tmp       PID_DIR=/tmp

set -u

# ---------- 路径解析 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
VENV_PY="$PROJECT_ROOT/.venv/bin/python"

# ---------- 配置 ----------
BACK_HOST="${BACK_HOST:-0.0.0.0}"
BACK_PORT="${BACK_PORT:-8000}"
FRONT_HOST="${FRONT_HOST:-0.0.0.0}"
FRONT_PORT="${FRONT_PORT:-5173}"

LOG_DIR="${LOG_DIR:-/tmp}"
PID_DIR="${PID_DIR:-/tmp}"

BACK_PID_FILE="$PID_DIR/fund_backend.pid"
FRONT_PID_FILE="$PID_DIR/fund_frontend.pid"
BACK_LOG="$LOG_DIR/fund_backend.log"
FRONT_LOG="$LOG_DIR/fund_frontend.log"

# ---------- 颜色 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
err()   { echo -e "${RED}[err]${NC} $*" >&2; }

# ---------- 工具 ----------
pid_alive() {
    local pid_file="$1"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null) || return 1
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

port_in_use() {
    lsof -ti tcp:"$1" 2>/dev/null | head -1
}

wait_for_port() {
    local port="$1" timeout="${2:-30}" i=0
    while (( i < timeout )); do
        if port_in_use "$port" > /dev/null; then
            # 还得多等 1-2 秒让服务完全就绪
            curl -fsS -m 2 "http://localhost:$port/" >/dev/null 2>&1 && return 0
        fi
        sleep 1
        (( i++ ))
    done
    return 1
}

# ---------- 后端 ----------
start_backend() {
    info "启动后端 (port $BACK_PORT)..."
    if pid_alive "$BACK_PID_FILE"; then
        warn "后端已在运行 (PID $(cat "$BACK_PID_FILE"))，跳过"
        return 0
    fi
    if [[ ! -x "$VENV_PY" ]]; then
        err ".venv/bin/python 不存在或不可执行：$VENV_PY"
        err "请先：uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r backend/requirements.txt"
        return 1
    fi

    local existing
    existing=$(port_in_use "$BACK_PORT")
    if [[ -n "$existing" ]]; then
        warn "端口 $BACK_PORT 已被 PID $existing 占用，尝试结束..."
        kill -9 "$existing" 2>/dev/null || true
        sleep 1
    fi

    cd "$BACKEND_DIR"
    nohup "$VENV_PY" -m uvicorn app.main:app --host "$BACK_HOST" --port "$BACK_PORT" > "$BACK_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$BACK_PID_FILE"
    disown 2>/dev/null || true

    if wait_for_port "$BACK_PORT" 30; then
        ok "后端已启动 PID=$pid  http://localhost:$BACK_PORT  (日志: $BACK_LOG)"
        return 0
    fi
    err "后端 30 秒内未就绪，查看日志：$BACK_LOG"
    return 1
}

stop_backend() {
    info "停止后端..."
    local pid="" ok=1
    pid_alive "$BACK_PID_FILE" && pid=$(cat "$BACK_PID_FILE")
    # 也兜底按端口清理（应付 PID 文件丢失 / 别人起的进程）
    local port_pid
    port_pid=$(port_in_use "$BACK_PORT")
    [[ -n "$port_pid" && "$port_pid" != "$pid" ]] && pid="$port_pid"

    if [[ -z "$pid" ]]; then
        warn "后端未运行"
        rm -f "$BACK_PID_FILE"
        return 0
    fi
    kill "$pid" 2>/dev/null && sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        warn "PID $pid 未响应 SIGTERM，发 SIGKILL"
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$BACK_PID_FILE"
    ok "后端已停止"
}

# ---------- 前端 ----------
start_frontend() {
    info "启动前端 (port $FRONT_PORT)..."
    if pid_alive "$FRONT_PID_FILE"; then
        warn "前端已在运行 (PID $(cat "$FRONT_PID_FILE"))，跳过"
        return 0
    fi
    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
        err "frontend/node_modules 不存在：$FRONTEND_DIR/node_modules"
        err "请先：cd frontend && npm install"
        return 1
    fi

    local existing
    existing=$(port_in_use "$FRONT_PORT")
    if [[ -n "$existing" ]]; then
        warn "端口 $FRONT_PORT 已被 PID $existing 占用，尝试结束..."
        kill -9 "$existing" 2>/dev/null || true
        sleep 1
    fi

    cd "$FRONTEND_DIR"
    nohup npm run dev -- --host "$FRONT_HOST" --port "$FRONT_PORT" > "$FRONT_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$FRONT_PID_FILE"
    disown 2>/dev/null || true

    if wait_for_port "$FRONT_PORT" 40; then
        ok "前端已启动 PID=$pid  http://localhost:$FRONT_PORT  (日志: $FRONT_LOG)"
        return 0
    fi
    err "前端 40 秒内未就绪，查看日志：$FRONT_LOG"
    return 1
}

stop_frontend() {
    info "停止前端..."
    local pid=""
    pid_alive "$FRONT_PID_FILE" && pid=$(cat "$FRONT_PID_FILE")
    local port_pid
    port_pid=$(port_in_use "$FRONT_PORT")
    [[ -n "$port_pid" && "$port_pid" != "$pid" ]] && pid="$port_pid"

    if [[ -z "$pid" ]]; then
        warn "前端未运行"
        rm -f "$FRONT_PID_FILE"
        return 0
    fi
    # vite dev 经常用 npm 父 + node 子两层；连父带子都要清
    local children
    children=$(pgrep -P "$pid" 2>/dev/null | tr '\n' ' ')
    kill "$pid" 2>/dev/null
    [[ -n "$children" ]] && kill $children 2>/dev/null
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null
        [[ -n "$children" ]] && kill -9 $children 2>/dev/null
    fi
    rm -f "$FRONT_PID_FILE"
    ok "前端已停止"
}

# ---------- 状态 / 日志 ----------
show_status() {
    echo "==== 后端 (port $BACK_PORT) ===="
    if pid_alive "$BACK_PID_FILE"; then
        local pid; pid=$(cat "$BACK_PID_FILE")
        echo -e "  PID: $pid  ${GREEN}running${NC}"
    else
        local p; p=$(port_in_use "$BACK_PORT")
        if [[ -n "$p" ]]; then
            echo -e "  PID: $p (未跟踪)  ${YELLOW}orphaned${NC}"
        else
            echo -e "  ${RED}stopped${NC}"
        fi
    fi
    echo "  日志: $BACK_LOG"

    echo "==== 前端 (port $FRONT_PORT) ===="
    if pid_alive "$FRONT_PID_FILE"; then
        local pid; pid=$(cat "$FRONT_PID_FILE")
        echo -e "  PID: $pid  ${GREEN}running${NC}"
    else
        local p; p=$(port_in_use "$FRONT_PORT")
        if [[ -n "$p" ]]; then
            echo -e "  PID: $p (未跟踪)  ${YELLOW}orphaned${NC}"
        else
            echo -e "  ${RED}stopped${NC}"
        fi
    fi
    echo "  日志: $FRONT_LOG"
}

show_logs() {
    local target="${1:-}"
    case "${target^^}" in
        BACK|BACKEND)
            [[ -f "$BACK_LOG" ]] || { err "日志不存在：$BACK_LOG"; return 1; }
            tail -n 100 -f "$BACK_LOG"
            ;;
        FRONT|FRONTEND)
            [[ -f "$FRONT_LOG" ]] || { err "日志不存在：$FRONT_LOG"; return 1; }
            tail -n 100 -f "$FRONT_LOG"
            ;;
        *)
            if [[ -f "$BACK_LOG" || -f "$FRONT_LOG" ]]; then
                tail -n 50 -f "$BACK_LOG" "$FRONT_LOG"
            else
                err "日志不存在"
                return 1
            fi
            ;;
    esac
}

usage() {
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# ---------- 主入口 ----------
cmd="${1:-start}"
shift || true

case "$cmd" in
    start)        start_backend && start_frontend && show_status ;;
    stop)         stop_frontend; stop_backend ;;
    restart)      stop_frontend; stop_backend; start_backend && start_frontend && show_status ;;
    backend)      start_backend ;;
    frontend)     start_frontend ;;
    status)       show_status ;;
    logs)         show_logs "${1:-}" ;;
    -h|--help|help) usage ;;
    *)            err "未知命令：$cmd"; usage ;;
esac