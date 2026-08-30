# 选基助手 (Fund Assistant)

基金投资辅助工具，支持 **QDII 额度监控、基金评测、ETF 双动量轮动、A 股行业板块监测、策略回测**。

部署形态：单 Docker 容器（nginx + uvicorn + APScheduler），适合 ARM 小盒子（N1 / 树莓派 / 群晖）。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [Docker 部署（推荐）](#docker-部署推荐)
- [本地开发](#本地开发)
- [项目结构](#项目结构)
- [功能模块详解](#功能模块详解)
- [API 接口](#api-接口)
- [数据源](#数据源)
- [更新日志](#更新日志)

---

## 功能特性

### 1. QDII 场外基金额度监控
- 监控 **33 只** QDII 场外基金的每日申购限额
- 按指数分类（标普500、纳斯达克100）
- 实时检测限额变化并高亮显示
- 自动汇总每日可投额度
- 工作日 10:00 推送飞书

### 2. ETF 双动量轮动策略
- 4 只代表性 ETF：创业板、红利低波、纳斯达克、黄金
- 激进型：综合评分 = 100% × 短期动量
- 保守型：综合评分 = 20 日夏普比率
- 满仓持有排名第 1 的 ETF
- 价格 < 60日线 → 强制卖出/观望
- 工作日 14:30 推送飞书

### 3. 基金评测
- 自选基金列表（默认页），显示粗略信息
- 点击详情进入完整评测页，展示指标 + 历史净值
- 综合评分 (0-100)
- 雷达图分析（收益能力、稳定性、风险收益、盈利概率、低波动）
- 历史净值走势（1y / 3y / 5y / 10y）
- 夏普、Sortino、卡玛、最大回撤、年化波动、盈利概率
- 同类基金 1 年收益百分位排名
- 东方财富基金搜索（代码 / 名称）
- 手动「更新数据」按钮

### 4. A 股行业板块监测
- **30+ 个** 中证一级 / 细分行业指数（主数据源，腾讯 qt.gtimg.cn）
- **45 个** 细分行业 ETF（新浪 hq.sinajs.cn，作为细分场景补充）
- 实时涨跌排名，强势/弱势信号
- 工作日 15:30 推送飞书

### 5. 策略回测
- 支持双动量轮动、定投（DCA）等策略
- 自定义标的池、回测区间、初始资金、benchmark
- 详细指标：总收益 / CAGR / Alpha / Sharpe / 最大回撤 / 胜率 / 盈亏比
- 日净值序列 + 交易明细可视化
- 多次回测对比

### 6. 最近活动聚合
- 首页 dashboard 自动聚合评测、回测、定时任务刷新记录
- 跨模块统一时间线

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + SQLite + APScheduler（in-process） |
| 前端 | Vue3 + Element Plus + ECharts + Vite |
| 推送 | 飞书 Open API（直连 HTTP） |
| 容器 | Docker + docker compose v2 + BuildKit |
| 调度 | APScheduler AsyncIOScheduler（容器内，替代外部 cron） |

---

## Docker 部署（推荐）

### 前置
- N1 / 任意 Linux 服务器（ARM64 或 x86_64）
- 已装 Docker + docker compose v2
- eMMC 紧张时建议 U 盘挂到 `/mnt/usb`，docker data-root 迁过去（防 eMMC 写满）

设置目标主机（**首次部署前导出一次即可**）：

```bash
# 格式: user@host，改成你自己的 N1 登录地址
export N1_HOST=root@192.168.50.254
# 浏览器访问用的纯 IP（从 $N1_HOST 派生，去掉 user@ 前缀）
export N1_IP="${N1_HOST#*@}"
```

> 也可以写到 `~/.zshrc` / `~/.bashrc` 持久化，避免每次重输。

### 步骤

```bash
# 1. SSH 进 N1
ssh "$N1_HOST"

# 2. 首次：填 .env
mkdir -p ~/fund-assistant && cd ~/fund-assistant
# 先把项目代码 rsync 过来（Mac 上执行）：
#   rsync -avz --delete --exclude='.venv' --exclude='data/' --exclude='.env' \
#     --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
#     --exclude='CLAUDE.md' --exclude='*.log' \
#     ./ "$N1_HOST":~/fund-assistant/
cp .env.example .env
nano .env   # 填 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID

# 3. 构建 + 启动
export DOCKER_BUILDKIT=1
docker compose build    # 首次 5-15 分钟（已配清华/华为镜像）
docker compose up -d

# 4. 健康检查
sleep 8
curl http://localhost/api/health

# 5. 浏览器访问 http://$N1_IP/
```

### 数据持久化

`./data/fund.db` 通过 bind mount 持久化在 N1 eMMC，重启容器不丢。

### 镜像优化

- apt / pip / npm 已配华为/清华镜像源，国内拉取稳定
- BuildKit `--mount=type=cache` 让 pip / npm 缓存不进镜像 layer
- 第二次构建只重算改动的层（~30 秒 - 3 分钟）

### 后续更新发布

```bash
# Mac 改完代码后
rsync -avz --delete --exclude='.venv' --exclude='data/' --exclude='.env' \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  --exclude='CLAUDE.md' --exclude='*.log' \
  ./ "$N1_HOST":~/fund-assistant/
ssh "$N1_HOST" 'cd ~/fund-assistant && docker compose build && docker compose up -d'
```

---

## 本地开发

```bash
# 后端
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 前端（另一终端）
cd frontend && npm install && npm run dev
```

或用 `./start.sh start` 一键启动前后端。

**手动跑数据脚本**（Docker 内由 scheduler 调，本地测试用）：
```bash
.venv/bin/python scripts/fetch_qdii.py
.venv/bin/python scripts/run_momentum.py
.venv/bin/python scripts/industry_ranking.py
```

---

## 项目结构

```
fund-assistant/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # FastAPI 入口 + lifespan（init_db + scheduler.start）
│   │   ├── routers/            # 8 个路由模块
│   │   ├── services/           # 业务逻辑（crawler / fund_data / fund_eval / scheduler / backtest）
│   │   ├── db/database.py      # SQLite + 表结构 + 迁移
│   │   └── models/schemas.py   # Pydantic schema
│   └── requirements.txt
│
├── frontend/                   # Vue3 前端
│   └── src/
│       ├── views/              # 6 个页面：Home / Qdii / FundEval / EtfMomentum / Industry / Backtest
│       ├── api/index.ts        # Axios 客户端
│       └── router/index.ts     # Vue Router
│
├── scripts/                    # 抓数据 + 推飞书（APScheduler 动态 import）
│   ├── feishu_sender.py        # 飞书 Open API 共享 send()
│   ├── fetch_qdii.py           # QDII 抓取 + 推送
│   ├── run_momentum.py         # ETF 动量 + 推送（同步 4 只 ETF 收盘价到 fund_nav）
│   └── industry_ranking.py     # 行业涨跌榜 + 推送
│
├── data/                       # SQLite 数据库（容器 bind mount）
│
├── Dockerfile                  # 多阶段 build（node → python-builder → python-slim runtime）
├── docker-compose.yml
├── supervisord.conf            # 容器内管 nginx + uvicorn
├── nginx.conf                  # 反代 /api → 127.0.0.1:8000
├── start.sh                    # 本地 dev 启动
├── CLAUDE.md                   # 项目详细文档（架构 / 部署 / API）
└── README.md                   # 本文件
```

---

## 功能模块详解

### QDII 场外基金额度监控

| 分类 | 数量 | 示例基金 |
|------|------|----------|
| 标普500 ETF联接 | 6 只 | 华夏标普500ETF联接 |
| 标普500 FOF | 3 只 | 天弘标普500发起(QDII-FOF) |
| 标普500 指数 | 4 只 | 摩根标普500指数 |
| 纳指100 ETF联接 | 12 只 | 广发纳指100ETF联接 |
| 纳指100 直接指数 | 8 只 | 摩根纳斯达克100指数 |

**数据来源**：
- 东方财富 F10：限购金额、费率、规模
- 天天基金：净值日期、申购/赎回状态、基金经理

### ETF 双动量轮动策略

跟踪的 ETF：

| 代码 | 名称 | 类型 |
|------|------|------|
| 159915 | 创业板ETF | 国内 |
| 512890 | 红利低波ETF | 红利 |
| 159941 | 纳指ETF | 美股 |
| 518880 | 黄金ETF | 黄金 |

策略逻辑：

```
激进型综合评分 = 短期动量 × 100% + 中期动量 × 0%
保守型综合评分 = 20日夏普比率

短期动量 = 近20日涨幅
中期动量 = 近60日涨幅

信号规则:
- 价格在60日线上方 且 评分 > 3: 买入
- 价格在60日线上方: 持有
- 价格在60日线下方: 卖出
```

### A 股行业板块监测

**30+ 中证指数（主数据源）** + **45 个细分 ETF（细分场景）**，强弱信号：

| 信号 | 涨跌幅 |
|------|--------|
| 强势 | > +2% |
| 偏强 | 0% ~ +2% |
| 偏弱 | -2% ~ 0% |
| 弱势 | < -2% |

### 基金评测指标

| 指标 | 说明 |
|------|------|
| 综合评分 | 0-100 分 |
| 近1/3/5年收益 | 历史收益率；数据不足显示"数据不足" |
| 夏普比率 | 风险调整收益 |
| Sortino 比率 | 下行风险调整收益 |
| 卡玛比率 | 年化收益 / 最大回撤 |
| 最大回撤 | 历史最大亏损 |
| 年化波动率 | 风险度量 |
| 盈利概率 | 正收益交易日占比 |
| 同类1y百分位 | 同类型基金近 1 年收益排名 |

---

## API 接口

完整 Swagger 文档：**`http://<host>/docs`**

### 核心端点速查

| 模块 | 关键端点 |
|------|---------|
| QDII | `GET /api/qdii/quota` · `POST /api/qdii/quota/refresh` |
| ETF | `GET /api/etf/momentum` · `POST /api/etf/momentum/refresh` |
| 行业 | `GET /api/industry/ranking` · `POST /api/industry/ranking/refresh` |
| 基金评测 | `GET /api/fund/favorites` · `GET /api/fund/eval/{code}` · `POST /api/fund/eval/{code}/refresh` |
| 回测 | `GET /api/backtest/strategies` · `POST /api/backtest/run` · `GET /api/backtest/runs` |
| 调度 | `GET /api/scheduler/status` · `POST /api/scheduler/run/{job_id}` |
| 飞书 | `POST /api/notify/test` · `POST /api/notify/send` |
| 活动 | `GET /api/activity/recent` |

---

## 数据源

| 功能 | 数据源 | URL |
|------|--------|-----|
| ETF 历史 K 线 | 新浪财经 | `money.finance.sina.com.cn` |
| ETF 实时价格 | 新浪财经 / 腾讯财经 | `hq.sinajs.cn` / `qt.gtimg.cn` |
| QDII 限额 | 东方财富 F10 | `fundf10.eastmoney.com` |
| 基金档案 / 净值 | 天天基金 / akshare | `fund.eastmoney.com` |
| 基金搜索 | 东方财富 | `fundsuggest.eastmoney.com` |
| 行业指数实时 | 腾讯财经 | `qt.gtimg.cn` |

---

## 注意事项

1. **数据爬取**：请遵守各网站的使用条款，不要过于频繁请求
2. **投资风险**：本工具仅供参考，**不构成投资建议**
3. **飞书凭据**：必须填 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID`，否则推送失败（不影响 API 使用）
4. **存储**：N1 eMMC 紧张时务必把 docker data-root 迁到 USB 盘（详见部署说明）
5. **镜像源**：Dockerfile 已配华为镜像源；如失效可改成 `mirrors.tuna.tsinghua.edu.cn`

---

## 许可证

本项目仅供个人学习研究使用。

---

## 更新日志

### v2.0.0 (2026-08-29)

**架构重构：完全 Docker 化 + APScheduler 替换 Hermes**
- 容器内 APScheduler 自调度，**不再依赖 Hermes agent**
- 飞书推送直连 Open API（`open-apis`），**不再走 hermes_cli subprocess**
- 多阶段 Dockerfile（node builder + python builder + python-slim runtime）
- supervisord 管 nginx + uvicorn（单容器架构）
- U 盘接管 docker data-root（解决 eMMC 写满问题）
- 镜像源换华为/清华（解决国内拉取超时）
- 新增 `notify` / `scheduler` / `activity` / `backtest` 四个 router
- 新增 `fund/eval/batch-refresh` / `industry/history` 等端点

### v1.2.0 (2026-07-02)
- 基金评测重构为「读 DB + refresh 写 DB」架构
- 新增自选基金功能
- 新增 Sortino 比率、卡玛比率、同类 1 年百分位
- 首次刷新拉取 5 年净值，后续增量更新
- 新增东方财富基金搜索
- ETF 双动量刷新时同步写入 `fund_nav`

### v1.1.0 (2026-06-29)
- 新增纳斯达克100场外基金监控（21只）
- QDII 通知增加限额变化检测和分类汇总
- ETF 动量策略改为满仓持有排名第 1
- 前端新增限额变化高亮显示

### v1.0.0 (2026-06-24)
- 初始版本
- QDII 额度监控
- ETF 双动量轮动
- 基金评测
- 行业板块监测