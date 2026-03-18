# 🧠 Personal AI Memory System
> 个人多模态知识记忆系统 · 多平台收藏夹 · 统一记忆 · 智能问答

把所有平台的收藏夹，变成一个可以对话的私人知识库。

---

## ✨ 核心能力

- **多平台统一接入**：YouTube、Twitter/X、GitHub、Pocket、Bilibili、微信收藏、抖音、小红书
- **多模态内容解析**：文本、视频（Whisper ASR）、图片（Qwen2-VL）、代码仓库、PDF
- **结构化记忆存储**：FAISS 向量索引 + SQLite 元数据，携带完整跨平台来源信息
- **标准化问答输出**：每次查询强制返回平台名称、内容名称、摘要、收藏时间、原始链接
- **智能总结与关联**：跨平台内容聚合总结，自动发现知识关联
- **语音播报**：XTTS 将回答转为语音输出（可选）

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd personal-ai-memory
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填入：
# - LLM_API_KEY（OpenAI 或 Anthropic）
# - TOKEN_MASTER_PASSWORD（本地加密密钥）
# - 至少一个平台的认证信息
```

### 3. 启动 Web API

```bash
python main.py serve
# API 文档：http://localhost:8000/docs
```

### 4. 交互式问答

```bash
python main.py interactive
```

---

## 📖 使用方式

### 命令行

```bash
# 查询记忆库
python main.py query "我最近收藏了哪些关于 LangGraph 的内容？"

# 同步平台（首次全量）
python main.py sync --full
python main.py sync --platform github

# 查看统计
python main.py stats
```

### API 接口

```bash
# 查询
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "我最近7天收藏了什么？"}'

# 同步 GitHub
curl -X POST http://localhost:8000/sync \
  -d '{"platform": "github", "full_sync": false}'

# 统计信息
curl http://localhost:8000/memories/stats
```

### 平台连接（OAuth 2.0）

```bash
# 获取 YouTube 授权 URL
curl http://localhost:8000/auth/youtube/connect
# → 返回 auth_url，在浏览器打开完成授权

# 设置小红书 Cookie（Cookie 模式）
curl -X POST http://localhost:8000/auth/xiaohongshu/cookie \
  -d '{"cookie": "从浏览器 DevTools 复制的 Cookie"}'
```

---

## 🏗️ 项目结构

```
personal-ai-memory/
├── platforms/              # 8个平台连接器
│   ├── base_connector.py   # 抽象基类
│   ├── pocket_connector.py
│   ├── youtube_connector.py
│   ├── twitter_connector.py
│   ├── github_connector.py
│   ├── bilibili_connector.py
│   ├── douyin_connector.py
│   ├── wechat_connector.py
│   └── xiaohongshu_connector.py
├── parsers/                # 多模态内容解析器
│   ├── text_parser.py      # 网页/文本
│   ├── audio_parser.py     # Whisper ASR
│   ├── vision_parser.py    # Qwen2-VL 图像理解
│   ├── video_parser.py     # 分层摘要策略
│   └── pdf_parser.py       # PDF 提取
├── agents/                 # 三个 Agent
│   ├── collector_agent.py  # 拉取+解析+入库
│   ├── memory_agent.py     # 去重+关联+重要性维护
│   └── knowledge_agent.py  # 意图解析+问答+输出
├── memory/                 # 存储层
│   ├── memory_schema.py    # 核心数据结构定义
│   ├── memory_store.py     # FAISS + SQLite 双写
│   └── importance_scorer.py
├── tools/                  # MCP 工具层
│   ├── mcp_tools.py        # 11个标准工具
│   ├── embedder.py         # Embedding 封装
│   └── memory_builder.py   # RawContent → Memory
├── auth/                   # 认证层
│   ├── token_store.py      # AES-256-GCM 加密存储
│   └── oauth_handler.py    # OAuth 2.0 流程
├── tts/
│   └── xtts_output.py      # 语音播报
├── tests/
│   └── test_phase1.py      # 集成测试
├── config.py               # 全局配置
├── main.py                 # 入口 (CLI + Web API)
├── requirements.txt
└── .env.example
```

---

## ⚙️ 开发原则

1. **Memory 字段只增不改** - `memory_schema.py` 向后兼容
2. **Embedding 只用 summary** - 严禁使用 `raw_content`
3. **Agent 通过 MCP 工具通信** - 不直接函数调用
4. **问答必须返回完整 QueryResult** - 5个必填字段不可缺
5. **Connector 独立测试后再集成** - 使用 Mock API 验证
6. **按 Phase 顺序开发** - Phase 1→2→3→4
7. **Cookie 模式平台单独隔离错误** - 返回 needs_reauth，不抛异常

---

## 🧪 运行测试

```bash
# Phase 1 集成测试
pytest tests/test_phase1.py -v

# 快速验证
python -c "from memory.memory_schema import Memory, QueryResult; print('✅ Schema OK')"
```

---

## 📊 问答示例输出

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
找到 3 条相关收藏（最近 7 天）：

① LangGraph Agent Tutorial
   平台：YouTube
   作者：LangChain Official
   收藏于：2026-03-14 · 类型：视频
   摘要：介绍如何用 LangGraph 构建 multi-agent workflow
   标签：LangGraph / Agent / workflow
   链接：https://youtube.com/watch?v=xxxxx

② Building LangGraph Agents
   平台：GitHub Star
   作者：langchain-ai
   收藏于：2026-03-13 · 类型：代码仓库
   摘要：LangGraph 官方示例仓库，含完整可运行代码
   标签：LangGraph / Python / 开源
   链接：https://github.com/langchain-ai/langgraph

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
综合总结：
你最近的 LangGraph 相关收藏横跨 YouTube 和 GitHub，
涵盖视频教程和官方示例代码，从入门到实践链路完整。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
