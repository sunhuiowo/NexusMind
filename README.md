# 🧠 Personal AI Memory System

> 跨平台个人知识记忆系统 · 把所有平台的收藏夹，变成可以对话的私人知识库

```
personal-ai-memory/
├── backend/     FastAPI 后端 + 三个 Agent + 8 个平台连接器
├── frontend/    React 18 + TypeScript 前端
├── docker-compose.yml
├── Makefile
└── start.sh     一键启动脚本
```

---

## ⚡ 快速启动

### 方式一：脚本启动（推荐）

```bash
# 1. 复制并配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少填入：
#   LLM_API_KEY=sk-...
#   TOKEN_MASTER_PASSWORD=your-password

# 2. 一键启动前后端
chmod +x start.sh && ./start.sh

# 前端: http://localhost:5173
# 后端 API: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

### 方式二：Docker Compose

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env

docker-compose up --build

# 访问 http://localhost:5173
```

### 方式三：手动分别启动

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py serve

# 前端（新终端）
cd frontend
npm install && npm run dev
```

---

## 🏗 架构概览

```
浏览器 (localhost:5173)
    │  Vite dev proxy /api → localhost:8000
    ▼
React 前端
    ├── Chat 问答页       → POST /query
    ├── Library 记忆库    → GET  /memories/stats
    ├── Platforms 平台    → GET  /auth/status
    ├── Sync 同步         → POST /sync
    └── Settings 设置

FastAPI 后端 (localhost:8000)
    ├── Knowledge Agent   意图识别 + 问答
    ├── Collector Agent   数据拉取 + 解析 + 入库
    ├── Memory Agent      关联维护 + 重要性更新
    ├── MCP Tool Server   11 个标准工具接口
    ├── FAISS             向量检索
    └── SQLite            结构化元数据
```

---

## 📁 目录结构

```
backend/
├── agents/          collector · memory · knowledge
├── platforms/       8 个平台连接器 (YouTube · Twitter · GitHub · Pocket · Bilibili · 微信 · 抖音 · 小红书)
├── parsers/         text · audio(Whisper) · vision(Qwen2-VL) · video · pdf
├── memory/          schema · store(FAISS+SQLite) · importance_scorer
├── tools/           mcp_tools · embedder · memory_builder
├── auth/            token_store(AES-256) · oauth_handler
├── tts/             xtts_output
├── config.py
├── main.py
└── requirements.txt

frontend/
├── src/
│   ├── api/         apiClient.ts · types.ts
│   ├── components/  ChatInput · MemoryCard · PlatformCard · QueryResultCard
│   ├── pages/       Chat · Library · Platforms · Sync · Settings
│   ├── store/       zustand stores
│   ├── ui/          Sidebar · Toast
│   └── utils/
├── package.json
└── vite.config.ts   (开发代理: /api → localhost:8000)
```

---

## 🔑 必填配置（backend/.env）

```bash
# LLM（选一个）
LLM_API_KEY=sk-...                    # OpenAI
# ANTHROPIC_API_KEY=sk-ant-...        # Anthropic
# LLM_BASE_URL=http://localhost:11434/v1  # Ollama

# 加密密钥（必须设置）
TOKEN_MASTER_PASSWORD=your-secure-password

# 平台凭证（按需填写，至少一个）
GITHUB_PAT=ghp_...                    # 最简单，直接用 PAT
POCKET_CONSUMER_KEY=...
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
```

---

## 🧪 运行测试

```bash
cd backend && pytest tests/test_phase1.py -v
```
