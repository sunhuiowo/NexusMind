#!/usr/bin/env bash
# start.sh — 一键启动前后端

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo -e "${BLUE}"
echo "  🧠  Personal AI Memory System"
echo "  ──────────────────────────────"
echo -e "${RESET}"

# ── 检查 .env ────────────────────────────────────────────────────────────────
if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo -e "${YELLOW}⚠️  未找到 backend/.env，从示例文件创建...${RESET}"
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
  echo -e "${RED}❗ 请编辑 backend/.env 填入 LLM_API_KEY 和 TOKEN_MASTER_PASSWORD 后重新运行${RESET}"
  exit 1
fi

# ── 检查 Python ───────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo -e "${RED}❌ 未找到 python3，请先安装 Python 3.10+${RESET}"
  exit 1
fi

# ── 检查 Node ────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo -e "${RED}❌ 未找到 node，请先安装 Node.js 18+${RESET}"
  exit 1
fi

# ── 安装后端依赖 ──────────────────────────────────────────────────────────────
echo -e "${BLUE}📦 安装后端依赖...${RESET}"
cd "$BACKEND_DIR"

# 优先使用 uv（推荐），回退到 pip
if command -v uv &>/dev/null; then
    echo -e "${BLUE}   使用 uv 管理依赖（推荐）${RESET}"
    uv sync
else
    echo -e "${YELLOW}   uv 未找到，使用 pip 安装${RESET}"
    # 使用虚拟环境（如果存在则复用）
    if [ ! -d ".venv" ]; then
      python3 -m venv .venv
    fi
    source .venv/bin/activate

    # 只安装核心依赖（不含大型 AI 模型）
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt 2>/dev/null || \
    pip install --quiet \
      fastapi uvicorn pydantic \
      openai anthropic \
      faiss-cpu \
      cryptography requests \
      python-dotenv \
      trafilatura beautifulsoup4 lxml \
      pdfplumber PyMuPDF 2>/dev/null || true
fi

echo -e "${GREEN}✓ 后端依赖就绪${RESET}"

# ── 安装前端依赖 ──────────────────────────────────────────────────────────────
echo -e "${BLUE}📦 安装前端依赖...${RESET}"
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install --silent
fi
echo -e "${GREEN}✓ 前端依赖就绪${RESET}"

# ── 启动后端 ──────────────────────────────────────────────────────────────────
echo -e "${BLUE}🚀 启动后端 (port 8001)...${RESET}"
cd "$BACKEND_DIR"

# Load .env and export all variables
set -a; source .env; set +a

# 启动后端服务
if [ -f ".venv/bin/python" ]; then
    # venv 环境（uv 或手动创建）
    .venv/bin/python main.py serve &
    BACKEND_PID=$!
else
    # 直接调用 python
    python3 main.py serve &
    BACKEND_PID=$!
fi
echo -e "${GREEN}✓ 后端 PID: $BACKEND_PID${RESET}"

# Wait for backend to be ready
echo -n "   等待后端就绪..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8001/health >/dev/null 2>&1; then
    echo -e " ${GREEN}✓${RESET}"
    break
  fi
  sleep 1
  echo -n "."
  if [ "$i" -eq 30 ]; then
    echo -e " ${YELLOW}(超时，继续启动前端)${RESET}"
  fi
done

# ── 启动前端 ──────────────────────────────────────────────────────────────────
echo -e "${BLUE}🎨 启动前端 (port 5173)...${RESET}"
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}✅ 启动成功！${RESET}"
echo ""
echo -e "   前端:    ${BLUE}http://localhost:5173${RESET}"
echo -e "   后端 API: ${BLUE}http://localhost:8001${RESET}"
echo -e "   API 文档: ${BLUE}http://localhost:8001/docs${RESET}"
echo ""
echo -e "${YELLOW}按 Ctrl+C 停止所有服务${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

# ── 等待退出信号 ──────────────────────────────────────────────────────────────
trap "echo ''; echo -e '${YELLOW}⏹ 正在停止服务...${RESET}'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo -e '${GREEN}✓ 已停止${RESET}'; exit 0" SIGINT SIGTERM

wait
