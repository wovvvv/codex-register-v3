#!/bin/bash
set -euo pipefail

# 所有运行时状态统一落到 /data，避免镜像重建时丢失 SQLite、日志和代理配置。
mkdir -p /data /data/.cache

if [ ! -f /data/proxies.txt ]; then
  cp /app/proxies.default.txt /data/proxies.txt
fi

touch /data/accounts.db /data/register.log

# 源码中直接使用 /app 下的固定文件名，这里用软链接把持久化文件映射回去。
ln -sf /data/accounts.db /app/accounts.db
ln -sf /data/proxies.txt /app/proxies.txt
ln -sf /data/register.log /app/register.log

# Camoufox 资源体积较大，默认不拉取；只有显式开启时才执行一次初始化。
if [ "${FETCH_CAMOUFOX:-0}" = "1" ] && [ ! -f /data/.camoufox_fetched ]; then
  python -m camoufox fetch
  touch /data/.camoufox_fetched
fi

# 容器启动时做幂等数据库初始化，然后直接拉起 WebUI。
python -m src.main db init
exec python -m src.main webui --host "${HOST:-0.0.0.0}" --port "${PORT:-7860}"
