# 选基助手项目

## 项目概述

基金投资辅助工具，支持 QDII 额度监控、基金评测、ETF 双动量轮动、A股行业板块监测、策略回测。

**部署形态**：单 Docker 容器（nginx + uvicorn via supervisord），适合 ARM 小盒子（N1/RPi/群晖）。
**调度**：容器内 APScheduler，**不依赖外部 agent / Hermes**。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + SQLite + APScheduler（in-process） |
| 前端 | Vue3 + Element Plus + ECharts + Vite |
| 推送 | 飞书 Open API（直连 HTTP，subprocess 调 hermes 已废弃） |
| 包管理 | [uv](https://github.com/astral-sh/uv)（替代 pip + venv + pyenv） |
| 容器 | Docker + docker compose v2 |

## 目录结构

```
fund-assistant/
├── .venv/           # uv 管理的 Python 3.12 venv（仅本地 dev 用）
├── backend/         # FastAPI 后端
│   ├── app/
│   │   ├── main.py            # FastAPI 入口（lifespan: init_db + scheduler.start）
│   │   ├── routers/           # 8 个 router
│   │   │   ├── qdii.py        # QDII 场外额度
│   │   │   ├── fund.py        # 基金评测 + 自选
│   │   │   ├── etf.py         # ETF 双动量
│   │   │   ├── industry.py    # 行业涨跌榜
│   │   │   ├── backtest.py    # 策略回测
│   │   │   ├── activity.py    # 最近活动聚合
│   │   │   ├── notify.py      # 飞书推送测试端点
│   │   │   └── scheduler.py   # 调度器状态 + 手动触发
│   │   ├── services/
│   │   │   ├── crawler.py     # 新浪/东方财富/腾讯数据爬虫
│   │   │   ├── fund_data.py   # 基金净值/基本信息
│   │   │   ├── fund_eval.py   # 评测指标计算
│   │   │   ├── scheduler.py   # APScheduler 包装（3 个 cron job）
│   │   │   └── backtest/      # 回测引擎 + 策略注册
│   │   ├── db/database.py     # SQLite + 表结构 + 迁移
│   │   └── models/schemas.py  # Pydantic schema
│   └── requirements.txt
├── frontend/        # Vue3 前端（npm run build → /dist）
├── scripts/         # 抓数据 + 推飞书（被 APScheduler 动态 import）
│   ├── feishu_sender.py       # 飞书 Open API 共享 send()
│   ├── fetch_qdii.py          # QDII 抓取 + 推送
│   ├── run_momentum.py        # ETF 动量 + 推送（同步 4 只 ETF 收盘价到 fund_nav）
│   └── industry_ranking.py    # 行业涨跌榜 + 推送
├── data/            # SQLite 数据库（容器 bind mount）
├── Dockerfile
├── docker-compose.yml
├── supervisord.conf # nginx + uvicorn
├── nginx.conf       # 反代 /api → 127.0.0.1:8000
└── start.sh         # 本地 dev（不用 docker）
```

## 数据流架构（重要）

QDII / ETF / Industry / Fund eval / Backtest **五个模块全部采用** "读 DB + cron 写 DB" 分离架构：

```
容器内 APScheduler → 调 scripts/*.run() → POST /api/{module}/.../refresh → 后端抓数据 + 写 DB
                                                       ↓
                                脚本（scripts/*.py）→ 读 DB → 飞书推送（Open API）
                                                       ↓
前端 onMounted / 点击"更新数据"按钮 → 直接读 DB（毫秒级返回）
                              ↑
                  POST refresh + 再 GET（手动触发）
```

- 前端 `onMounted` **只**读 DB（不触发抓数据）
- "更新数据"按钮 POST refresh（触发抓数据 + 写库）+ 紧接着 GET（拿最新数据显示）
- 每个模块的 router 都拆成 `read_*_from_db()` + `.../refresh` 两个端点
- scheduler 通过 `__import__(module)` 动态加载 scripts，调用其 `run()` 异步函数

## 容器内调度（替代 Hermes）

3 个定时任务注册在 APScheduler（`backend/app/services/scheduler.py`）：

| job_id | 触发 | 脚本 |
|--------|------|------|
| `qdii_daily` | 工作日 10:00 | `scripts/fetch_qdii.py::run` |
| `etf_momentum` | 工作日 14:30 | `scripts/run_momentum.py::run` |
| `industry_ranking` | 工作日 15:30 | `scripts/industry_ranking.py::run` |

调度参数：
- `misfire_grace_time=300s` 后端重启 / 卡住 5 分钟内能补上
- `coalesce=True` 多次堆积合并成一次
- `max_instances=1` 永不并发

**环境变量控制**：
- `SCHEDULER_ENABLED=true`（默认）— 设为 `false` 关闭（手动测试场景）
- `SCHEDULER_TIMEZONE=Asia/Shanghai`

**手动触发**（调试用）：
```bash
curl -X POST http://localhost/api/scheduler/run/qdii_daily
curl -X POST http://localhost/api/scheduler/run/etf_momentum
curl -X POST http://localhost/api/scheduler/run/industry_ranking
```

**查看状态**：
```bash
curl http://localhost/api/scheduler/status
```

## 飞书推送

所有飞书消息走 **`scripts/feishu_sender.py`** 的 `send()`，**直连飞书 Open API**（不再走 hermes_cli subprocess）。

需要的环境变量（在容器环境里注入，见 `docker-compose.yml`）：

```bash
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx      # 飞书应用 App ID
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx      # 飞书应用 App Secret
FEISHU_CHAT_ID=oc_xxxxxxxxxxxxxxxx      # 目标群 chat_id（不受群改名影响）
```

**API 端点**（注意是 `open-apis` 复数）：
- `POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`
- `POST https://open.feishu.cn/open-apis/message/v4/send`

`feishu_sender.send(message, target=None)` 行为：
- `target` 以 `oc_` 开头 → 覆盖默认 chat_id
- 进程内缓存 token（剩余 < 600s 时主动刷新）
- 失败重试 3 次（0s / 30s / 60s 退避）
- 彻底失败 → `sys.exit(1)`，APScheduler 视为 job 异常

**手动测试推送**（不依赖 cron）：
```bash
curl -X POST http://localhost/api/notify/test
curl -X POST http://localhost/api/notify/send \
  -H "Content-Type: application/json" \
  -d '{"message":"手动消息内容"}'
curl http://localhost/api/notify/status    # 看凭据是否配置
```

## Docker 部署

> **环境变量约定**：所有部署命令用 `$N1_HOST`（格式 `user@host`），首次部署前 `export` 一次即可：
> ```bash
> export N1_HOST=root@192.168.50.254    # 改成你自己的 N1 地址
> ```

### N1 单容器（典型场景）

```bash
# 1. SSH 进 N1，确认已装 docker + compose v2 + 已插 USB 盘
ssh "$N1_HOST"

# 2. 首次部署：填 .env
mkdir -p ~/fund-assistant && cd ~/fund-assistant
cp .env.example .env
nano .env   # 填 FEISHU_APP_ID / SECRET / CHAT_ID

# 3. 在 Mac 上同步源码（不会覆盖 .env）
cd /Users/upstream/claude/fund/fund-assistant
rsync -avz --delete --exclude='.venv' --exclude='data/' --exclude='.env' \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  --exclude='CLAUDE.md' --exclude='*.log' \
  ./ "$N1_HOST":~/fund-assistant/

# 4. 在 N1 上构建 + 启动
ssh "$N1_HOST"
cd ~/fund-assistant
docker compose build
docker compose up -d

# 5. 健康检查
curl http://localhost/api/health
```

### 数据持久化

`docker-compose.yml`：
```yaml
volumes:
  - ./data:/app/data   # SQLite + qdii-cache
```

DB 文件在 N1 eMMC（绑定挂载），Docker 镜像/容器在 USB 盘（`/mnt/usb/docker`，避免 eMMC 写满）。

### 镜像优化（已配置）

- 华为镜像源替换 deb.debian.org + PyPI + npm
- BuildKit `--mount=type=cache` 让 pip / npm 缓存不进镜像 layer
- data-root 迁到 U 盘（首次启动前 `daemon.json` 配 `"data-root": "/mnt/usb/docker"`）

### 端口映射

容器内：`uvicorn:8000` + `nginx:80`（supervisord 管理，nginx 兜底）
对外：N1 上 `:80` 端口 → 容器 `:80`

## 后续代码更新发布

```bash
# Mac 改完代码后：
rsync -avz --delete --exclude='.venv' --exclude='data/' --exclude='.env' \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  --exclude='CLAUDE.md' --exclude='*.log' \
  ./ "$N1_HOST":~/fund-assistant/

ssh "$N1_HOST" 'cd ~/fund-assistant && docker compose build && docker compose up -d'
```

**增量 build 命中规则**：
- 只改 `backend/*.py` 业务代码 → Stage 1/2 CACHED，只跑 Stage 3（~30 秒）
- 改了 `requirements.txt` → Stage 2 失效（~3-8 分钟）
- 改了 `Dockerfile` → 全失效（~5-15 分钟）

## API 接口清单

**根路径**：`/` `GET` 返回 API 信息；`/health` `GET` 健康检查；`/docs` `GET` Swagger UI（推荐看全 API）。

### QDII 额度（`/api/qdii`）
- `GET /quota` 读最新额度列表
- `POST /quota/refresh` 触发爬虫 + 写库
- `GET /quota/history?code=&days=` 历史
- `GET /quota/etf_link|fof|index|ndx_etf_link|ndx_direct` 分类查询
- `GET /quota/{code}` 单只详情

### ETF 双动量（`/api/etf`）
- `GET /momentum?strategy=aggressive|conservative` 读最新动量
- `POST /momentum/refresh` 触发计算 + 写库（同步把 4 只 ETF 收盘价写 fund_nav）
- `GET /candidates` 静态候选 ETF
- `GET /history?code=&days=` 历史
- `GET /detail/{code}` 单只详情
- `GET /compare-sources` 新浪 vs 腾讯数据源对比

### 行业板块（`/api/industry`）
- `GET /ranking` 读排名（从 DB）
- `POST /ranking/refresh` 触发抓
- `GET /funds?industry=` 按行业查
- `GET /list` 静态配置（30+ 中证一级/细分 + 45 个 ETF 代理）
- `GET /history?code=&days=` 历史

### 基金评测（`/api/fund`）
- `GET /favorites` 自选列表
- `POST /favorites/{code}` 加自选
- `DELETE /favorites/{code}` 删自选
- `GET /evaluated` 已评测列表
- `GET /eval/{code}` 读评测（不抓）
- `GET /eval/history?code=&days=` 历史
- `POST /eval/{code}/refresh` 抓 + 写库
- `POST /eval/batch-refresh` 批量刷新（端点保留，无 cron 调）
- `GET /history/{code}?period=1y|3y|5y|10y` 历史净值
- `GET /search?keyword=` 东方财富基金搜索
- `GET /info/{code}` 基本信息

### 基金回测（`/api/backtest`）
- `GET /strategies` 支持的策略列表
- `POST /run` 跑回测
- `GET /runs?strategy_type=&limit=` 历史回测
- `GET /runs/{id}` 单次详情
- `GET /runs/{id}/equity` 每日净值序列
- `GET /runs/{id}/trades` 交易明细
- `POST /compare` 对比多次（`{"run_ids":[1,2]}`）
- `DELETE /runs/{id}` 删除

### 调度器（`/api/scheduler`）
- `GET /status` 调度器状态 + 所有 job
- `POST /run/{job_id}` 手动触发（异步后台）

### 飞书通知（`/api/notify`）
- `GET /status` 推送凭据状态
- `POST /test` 发固定测试消息
- `POST /send` 发自定义消息（`{"message":"...", "target":"oc_..."}`）

### 最近活动（`/api/activity`）
- `GET /recent?limit=12` 最近 N 条操作（评测/回测/cron 刷新）

## 数据库 schema

8 张表，统一存 SQLite `./data/fund.db`：

| 表 | 用途 |
|----|------|
| `qdii_quota` | QDII 场外额度（按 code+update_time 唯一，保留历史） |
| `fund_nav` | 基金 / ETF 净值（按 code+date 唯一） |
| `momentum_history` | ETF 动量计算记录（按 code+calc_time 唯一） |
| `industry_funds` | 行业涨跌记录（按 code+update_time 唯一，保留历史） |
| `fund_info` | 基金基本信息（code 主键） |
| `fund_eval_history` | 评测历史（按 code+eval_time 唯一） |
| `user_favorite_funds` | 自选基金 |
| `backtest_runs` + `backtest_daily_values` + `backtest_trades` | 回测 3 张表 |

**迁移机制**：init_db() 启动时自动 ALTER TABLE ADD COLUMN 补缺列（幂等）。

## 启动方式（本地 dev，不用 docker）

```bash
# 后端
cd fund-assistant
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 前端（另一个终端）
cd frontend && npm install && npm run dev
```

或跑 `./start.sh start`（封装了 backend + frontend 启动）。

**手动跑数据脚本**（本地 dev 用，Docker 内由 scheduler 调用）：
```bash
.venv/bin/python scripts/fetch_qdii.py
.venv/bin/python scripts/run_momentum.py
.venv/bin/python scripts/industry_ranking.py
```