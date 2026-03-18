# Makefile — Personal AI Memory System

.PHONY: help dev install install-backend install-frontend \
        build test sync-all docker-up docker-down clean

# Default target
help:
	@echo ""
	@echo "  🧠 Personal AI Memory System"
	@echo ""
	@echo "  make dev              一键启动前后端开发服务器"
	@echo "  make install          安装全部依赖"
	@echo "  make install-backend  仅安装后端依赖"
	@echo "  make install-frontend 仅安装前端依赖"
	@echo "  make build            构建前端生产包"
	@echo "  make test             运行后端测试"
	@echo "  make sync-all         触发全平台全量同步"
	@echo "  make docker-up        Docker Compose 启动"
	@echo "  make docker-down      Docker Compose 停止"
	@echo "  make clean            清理缓存文件"
	@echo ""

dev:
	@chmod +x start.sh && ./start.sh

install: install-backend install-frontend

install-backend:
	@echo "📦 安装后端依赖..."
	@cd backend && pip install -r requirements.txt
	@echo "✓ 后端依赖就绪"

install-frontend:
	@echo "📦 安装前端依赖..."
	@cd frontend && npm install
	@echo "✓ 前端依赖就绪"

build:
	@echo "🔨 构建前端..."
	@cd frontend && npm run build
	@echo "✓ 构建产物在 frontend/dist/"

test:
	@echo "🧪 运行后端测试..."
	@cd backend && python -m pytest tests/ -v

sync-all:
	@echo "🔄 触发全平台全量同步..."
	@cd backend && python main.py sync --full

backend-only:
	@echo "🚀 仅启动后端..."
	@cd backend && python main.py serve

frontend-only:
	@echo "🎨 仅启动前端..."
	@cd frontend && npm run dev

docker-up:
	@docker-compose up --build -d
	@echo "✓ 服务已启动: http://localhost:5173"

docker-down:
	@docker-compose down
	@echo "✓ 服务已停止"

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ 缓存已清理"
