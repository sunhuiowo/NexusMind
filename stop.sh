#!/usr/bin/env bash
# stop.sh — 一键停止所有服务

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${YELLOW}⏹ 正在停止服务...${RESET}"

# 停止前端 (Vite)
VITE_PIDS=$(pgrep -f "vite" 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
    echo -e "  ${YELLOW}停止前端: $VITE_PIDS${RESET}"
    echo "$VITE_PIDS" | xargs kill -9 2>/dev/null || true
fi

# 停止后端 (Python/FastAPI)
PY_PIDS=$(pgrep -f "python.*main.py" 2>/dev/null || true)
if [ -n "$PY_PIDS" ]; then
    echo -e "  ${YELLOW}停止后端: $PY_PIDS${RESET}"
    echo "$PY_PIDS" | xargs kill -9 2>/dev/null || true
fi

# 也尝试停止 uvicorn
UV_PIDS=$(pgrep -f "uvicorn" 2>/dev/null || true)
if [ -n "$UV_PIDS" ]; then
    echo -e "  ${YELLOW}停止 uvicorn: $UV_PIDS${RESET}"
    echo "$UV_PIDS" | xargs kill -9 2>/dev/null || true
fi

echo -e "${GREEN}✓ 已停止所有服务${RESET}"
