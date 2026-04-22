# 🧠 NexusMind

> 跨平台个人知识系统 · 你的第二大脑，把所有平台的收藏夹，变成可以对话的知识库

```
nexusmind/
├── backend/     FastAPI 后端 + Agent + 8 个平台连接器
├── frontend/    React 18 + TypeScript 前端
├── docker-compose.yml
└── start.sh     一键启动脚本
```

---

## ⚡ 快速启动

### 环境要求
- Python 3.10+
- Node.js 18+
- uv（推荐）: `pip install uv`

### 方式一：uv + 脚本（推荐）

```bash
# 1. 复制并配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 和 TOKEN_MASTER_PASSWORD

# 2. 使用 uv 安装依赖
cd backend && uv sync

# 3. 一键启动
chmod +x start.sh && ./start.sh
```

### 方式二：Docker Compose

```bash
cp backend/.env.example backend/.env
docker-compose up --build
```

### 方式三：手动分别启动

```bash
# 后端
cd backend && uv sync && uv run python main.py serve

# 前端（新终端）
cd frontend && npm install && npm run dev
```

---

## 🔑 必填配置（backend/.env）

```bash
# LLM（必填）
LLM_API_KEY=sk-...                    # OpenAI
# 或使用 Anthropic/MiniMax 等兼容 API

# 加密密钥（必须设置）
TOKEN_MASTER_PASSWORD=your-secure-password

# 平台凭证（按需填写）
GITHUB_PAT=ghp_...                    # GitHub
```

---

## 🏗 架构概览

```
浏览器 (localhost:5173)
    │  Vite dev proxy /api → localhost:8001
    ▼
React 前端
    ├── Chat 问答页       → POST /query
    ├── Library 记忆库    → GET  /memories/stats
    ├── Platforms 平台    → GET  /auth/status
    ├── Sync 同步         → POST /sync
    └── Settings 设置

FastAPI 后端 (localhost:8001)
    ├── Knowledge Agent   意图识别 + 问答
    ├── Collector Agent   数据拉取 + 解析 + 入库
    ├── Memory Agent      关联维护 + 重要性更新
    ├── Code Agent        Claude Code 风格工具执行
    ├── FAISS             向量检索
    └── SQLite            结构化元数据
```

---

## 📁 目录结构

```
backend/
├── agents/          collector · memory · knowledge · code
├── platforms/       8 个平台连接器
├── memory/          FAISS + SQLite 存储
├── tools/           mcp_tools · exec_tools · llm
├── auth/            token_store(AES-256) · oauth_handler
├── config.py
├── main.py
└── pyproject.toml   # uv 依赖管理

frontend/
├── src/
│   ├── api/         apiClient.ts
│   ├── components/  ChatPanel · MemoryCard
│   ├── pages/       Chat · Library · Platforms
│   └── store/       zustand stores
├── package.json
└── vite.config.ts
```

---

## 🧪 运行测试

```bash
cd backend && pytest tests/test_phase1.py -v
```
