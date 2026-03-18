"""
parsers/text_parser.py
文本 / 网页内容解析器
使用 trafilatura 提取主体正文，清理导航栏广告
"""

import logging
import re
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


def parse_text(content: str) -> str:
    """清洗纯文本，去除多余空白和特殊字符"""
    if not content:
        return ""
    # 合并多余空行
    content = re.sub(r'\n{3,}', '\n\n', content)
    # 去除多余空格
    content = re.sub(r'[ \t]+', ' ', content)
    return content.strip()


def parse_webpage(url: str, fallback_content: str = "") -> str:
    """
    提取网页主体正文，清理导航栏广告
    优先使用 trafilatura，降级到 BeautifulSoup
    """
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
            if text:
                return parse_text(text)
    except ImportError:
        logger.debug("trafilatura 未安装，使用降级方案")
    except Exception as e:
        logger.warning(f"[TextParser] trafilatura 解析失败 {url}: {e}")

    # 降级：BeautifulSoup
    try:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PersonalAIMemory/1.0)"
        })
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # 删除无关元素
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "advertisement", "iframe", "noscript"]):
            tag.decompose()

        # 优先取 article > main > body
        for selector in ["article", "main", "[role='main']", ".content",
                          "#content", ".post-body", "body"]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return parse_text(text)

    except ImportError:
        logger.debug("bs4 未安装")
    except Exception as e:
        logger.warning(f"[TextParser] BeautifulSoup 解析失败 {url}: {e}")

    # 最终降级：返回已有内容
    return parse_text(fallback_content)


def parse_markdown(content: str) -> str:
    """解析 Markdown 文档，提取纯文本"""
    try:
        import markdown
        from bs4 import BeautifulSoup
        html = markdown.markdown(content)
        soup = BeautifulSoup(html, "html.parser")
        return parse_text(soup.get_text(separator="\n"))
    except ImportError:
        # 降级：简单去除 Markdown 标记
        content = re.sub(r'#{1,6}\s+', '', content)       # 标题
        content = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', content)  # 粗体/斜体
        content = re.sub(r'`{1,3}[^`]*`{1,3}', '', content)        # 代码
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content) # 链接
        content = re.sub(r'^[-*+]\s+', '', content, flags=re.MULTILINE)  # 列表
        return parse_text(content)


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list:
    """
    将长文本按语义边界切块
    优先使用 LangChain SemanticChunker，降级到固定窗口切分
    """
    if len(text) <= chunk_size:
        return [text]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " "],
        )
        return splitter.split_text(text)
    except ImportError:
        pass

    # 降级：简单固定窗口
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
