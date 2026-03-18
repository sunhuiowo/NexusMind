"""
parsers/pdf_parser.py
PDF 解析器 - 保留章节结构，分段提取
使用 pdfplumber / PyMuPDF
"""

import logging
import os
from typing import List, Dict, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


@staticmethod
def _clean_text(text: str) -> str:
    import re
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_pdf(
    source: str,  # 本地路径 或 URL
    max_pages: int = 50,
) -> Dict:
    """
    解析 PDF，提取文本和章节结构
    返回: {text: str, pages: [{page_num, text}], title: str}
    """
    # 下载远程 PDF
    local_path = source
    if source.startswith("http://") or source.startswith("https://"):
        local_path = _download_pdf(source)
        if not local_path:
            return {"text": "", "pages": [], "title": ""}

    # 优先 pdfplumber
    result = _parse_with_pdfplumber(local_path, max_pages)
    if result and result.get("text"):
        return result

    # 降级 PyMuPDF
    result = _parse_with_pymupdf(local_path, max_pages)
    if result and result.get("text"):
        return result

    return {"text": "", "pages": [], "title": ""}


def _parse_with_pdfplumber(path: str, max_pages: int) -> Optional[Dict]:
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber 未安装")
        return None

    try:
        pages_content = []
        all_text = []

        with pdfplumber.open(path) as pdf:
            title = pdf.metadata.get("Title", "") if pdf.metadata else ""
            total = min(len(pdf.pages), max_pages)

            for i, page in enumerate(pdf.pages[:total]):
                text = page.extract_text() or ""
                import re
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    pages_content.append({"page_num": i + 1, "text": text})
                    all_text.append(text)

        full_text = "\n\n".join(all_text)
        return {"text": full_text, "pages": pages_content, "title": title}

    except Exception as e:
        logger.warning(f"[PDFParser] pdfplumber 解析失败: {e}")
        return None


def _parse_with_pymupdf(path: str, max_pages: int) -> Optional[Dict]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF 未安装")
        return None

    try:
        import re
        pages_content = []
        all_text = []

        doc = fitz.open(path)
        title = doc.metadata.get("title", "") if doc.metadata else ""
        total = min(doc.page_count, max_pages)

        for i in range(total):
            page = doc[i]
            text = page.get_text("text") or ""
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                pages_content.append({"page_num": i + 1, "text": text})
                all_text.append(text)

        doc.close()
        full_text = "\n\n".join(all_text)
        return {"text": full_text, "pages": pages_content, "title": title}

    except Exception as e:
        logger.warning(f"[PDFParser] PyMuPDF 解析失败: {e}")
        return None


def _download_pdf(url: str) -> Optional[str]:
    """下载 PDF 到临时文件"""
    try:
        import requests
        import tempfile
        resp = requests.get(url, timeout=60, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PersonalAIMemory/1.0)"
        })
        resp.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.error(f"[PDFParser] PDF 下载失败 {url}: {e}")
        return None


def chunk_pdf(pages: List[Dict], chunk_size: int = 1000) -> List[str]:
    """将 PDF 页面内容分块"""
    chunks = []
    current = ""

    for page in pages:
        text = page.get("text", "")
        if len(current) + len(text) > chunk_size:
            if current:
                chunks.append(current.strip())
            current = text
        else:
            current += "\n" + text

    if current.strip():
        chunks.append(current.strip())

    return chunks
