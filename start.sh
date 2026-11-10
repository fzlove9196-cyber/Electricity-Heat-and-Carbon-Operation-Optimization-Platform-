#!/usr/bin/env bash
# 一键启动（后台常驻 + 崩溃自动重启）。用法: ./start.sh   停止: ./stop.sh
cd "$(dirname "$0")"; mkdir -p logs
ROOT="$(pwd)"
if [ -z "${PY:-}" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
  elif [ -x /workspace/sdco-env/bin/python ]; then
    PY=/workspace/sdco-env/bin/python
  else
    PY="${SDCO_PYTHON:-python3}"
  fi
fi
PORT=${PORT:-8080}; HOST=${HOST:-0.0.0.0}
[ -f .env ] || cp .env.example .env
if [ -f logs/supervisor.pid ] && kill -0 "$(cat logs/supervisor.pid)" 2>/dev/null; then echo "已在运行 (pid $(cat logs/supervisor.pid))"; exit 0; fi
nohup bash -c "while true; do $PY -m uvicorn app.main:app --host $HOST --port $PORT >> logs/server.log 2>&1; echo \"[\$(date)] server exited \$?, restarting in 3s\" >> logs/server.log; sleep 3; done" >/dev/null 2>&1 &
echo $! > logs/supervisor.pid
for i in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && { echo "✅ 已启动: http://127.0.0.1:$PORT  (日志 logs/server.log)"; exit 0; }; sleep 1; done
echo "⚠️ 启动超时，请查看 logs/server.log"; exit 1
