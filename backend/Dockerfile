# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（PDF 解析需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（分层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn pydantic \
    openai anthropic \
    faiss-cpu \
    cryptography requests \
    python-dotenv \
    trafilatura beautifulsoup4 lxml \
    pdfplumber PyMuPDF

# 复制源码
COPY . .

# 数据目录
RUN mkdir -p data/auth data/vectors

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
