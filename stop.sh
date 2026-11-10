#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ -f logs/supervisor.pid ]; then P=$(cat logs/supervisor.pid); kill "$P" 2>/dev/null; pkill -P "$P" 2>/dev/null; rm -f logs/supervisor.pid; fi
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1; echo "已停止"
