#!/usr/bin/env bash
# Stop only this repository's server. Never pkill every uvicorn on the machine
# (that would also kill other instances, e.g. a second port or a shared host).
cd "$(dirname "$0")"
if [ -f logs/supervisor.pid ]; then
  P=$(cat logs/supervisor.pid)
  kill "$P" 2>/dev/null
  pkill -P "$P" 2>/dev/null
  rm -f logs/supervisor.pid
fi
PORT=${PORT:-8080}
# Prefer the process listening on PORT.
pid=""
if command -v ss >/dev/null 2>&1; then
  pid=$(ss -lptn "sport = :${PORT}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1)
fi
if [ -z "$pid" ] && command -v lsof >/dev/null 2>&1; then
  pid=$(lsof -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
fi
if [ -n "$pid" ]; then
  kill "$pid" 2>/dev/null || true
  sleep 1
  echo "已停止 (port $PORT, pid $pid)"
else
  echo "未发现监听 $PORT 的进程（若用了 start.sh 的 supervisor，已尝试结束 logs/supervisor.pid）"
fi
