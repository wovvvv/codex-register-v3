# 先构建 React 前端静态资源，再组装 Python/Playwright 运行时镜像。
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build

COPY webui_frontend ./webui_frontend

# 前端产物输出到 /build/src/webui/static，供 FastAPI 直接托管。
RUN cd webui_frontend \
    && npm install \
    && npm run build


# 运行时使用 Python 3.11，满足项目声明的最低版本要求。
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/data/.cache \
    HOST=0.0.0.0 \
    PORT=7860

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY proxies.txt ./proxies.default.txt
COPY docker/entrypoint.sh /entrypoint.sh
COPY --from=frontend-builder /build/src/webui/static ./src/webui/static

# Camoufox/Firefox 依赖 GTK3；仅装最小缺失库，避免继续在运行期崩溃。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgtk-3-0 \
        libdbus-glib-1-2 \
    && rm -rf /var/lib/apt/lists/*

# 保持运行目录源码完整，直接按当前仓库结构启动模块入口。
RUN pip install --no-cache-dir . \
    && chmod +x /entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/entrypoint.sh"]
