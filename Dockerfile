# ============================================================
# Stage 1: Frontend builder (Node)
# ============================================================
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build

# 仅 copy package 文件触发 npm ci 缓存
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# 复制源码并 build
COPY frontend/ ./
RUN npm run build
# 产物在 /build/dist


# ============================================================
# Stage 2: Backend deps installer (Python)
# ============================================================
FROM python:3.12-slim-bookworm AS backend-builder

WORKDIR /build

# pandas / lxml / cffi 等需要 C 编译的 wheel 在 slim 下也能装，
# 但保险起见装上 build-essential + 头文件（同一层缓存）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
# --mount=type=cache 让 pip 缓存落到 BuildKit 缓存（不进镜像 layer），
# 节省 N1 eMMC ~300MB；重复 build 还能命中缓存。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ============================================================
# Stage 3: Runtime（python-slim + nginx + supervisord）
# ============================================================
FROM python:3.12-slim-bookworm

# N1 时区 + Python 内存优化（py3.12 默认 pymalloc 偶发碎片，
# 改 glibc malloc 在长跑 cron 任务下更稳；-X tracemalloc=0 略省 RSS）
ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONMALLOC=malloc \
    PYTHONPATH=/app

# Runtime 库：lxml → libxml2/libxslt1.1；cffi → libffi8；nginx；supervisord；tzdata；curl（healthcheck）
RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
        tzdata \
        libxml2 \
        libxslt1.1 \
        libffi8 \
        curl \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（从 builder 复制）
COPY --from=backend-builder /install /usr/local

# 前端构建产物（nginx 静态文件目录）
COPY --from=frontend-builder /build/dist /usr/share/nginx/dist

# 应用代码
WORKDIR /app
COPY backend/ ./backend/
COPY scripts/ ./scripts/

# 配置
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

# 数据目录（运行时由卷挂载覆盖）
RUN mkdir -p /app/data /app/data/qdii-cache

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fsS http://127.0.0.1/api/health || exit 1

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
