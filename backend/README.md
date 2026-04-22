# NexusMind Backend

See the root [README.md](../README.md) for full project documentation.

## 快速开始

```bash
# 安装 uv（推荐）
pip install uv

# 安装依赖
uv sync

# 启动 API 服务
uv run python main.py serve

# 或激活虚拟环境后运行
source .venv/bin/activate
python main.py serve
```

## 环境变量

复制 `.env.example` 为 `.env` 并配置：

```bash
LLM_API_KEY=sk-...           # OpenAI 或兼容 API
TOKEN_MASTER_PASSWORD=...     # 加密密钥（必填）
```

## CLI 命令

```bash
python main.py query "问题"      # 查询记忆
python main.py sync --full       # 全量同步
python main.py stats             # 查看统计
python main.py interactive       # 交互模式
```
