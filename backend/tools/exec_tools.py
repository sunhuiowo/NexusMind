"""
执行工具 - bash, file_read, file_write, glob

安全考虑：
- 工作目录隔离
- 命令黑名单
- 超时控制
"""

import glob as glob_module
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Bash ──────────────────────────────────────────────────────────────────────

def bash(command: str, timeout: int = 30, work_dir: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    执行 bash 命令（沙箱环境）

    Args:
        command: 要执行的命令
        timeout: 超时秒数
        work_dir: 工作目录

    Returns:
        {"success": bool, "stdout": str, "stderr": str, "returncode": int}
    """
    # 危险命令黑名单
    DANGEROUS = [
        r"rm\s+-rf\s+/(?:\*)?",      # rm -rf /
        r"rm\s+-rf\s+/System",        # rm -rf /System
        r"rm\s+-rf\s+/boot",          # rm -rf /boot
        r"mkfs",                       # 格式化磁盘
        r":\(\)\{:|:&\};:",           # fork bomb
        r"dd\s+if=.*of=/dev/sd",      # 直接写磁盘
        r">\s*/etc/passwd",           # 覆写系统文件
        r"chmod\s+-R\s+777\s+/",      # 开放全部权限
        r"wget.*\|\s*sh",             # 远程代码注入
        r"curl.*\|\s*sh",             # 远程代码注入
    ]

    for pattern in DANGEROUS:
        if re.search(pattern, command):
            return {
                "success": False,
                "error": f"危险命令: {pattern}",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
            }

    # 超时保护
    if timeout > 120:
        timeout = 120  # 最多2分钟

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            env={**os.environ, "HOME": work_dir or "/tmp"},
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:10000],  # 限制输出长度
            "stderr": result.stderr[:5000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"命令超时 ({timeout}s)",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }


# ── File Read ────────────────────────────────────────────────────────────────

def file_read(path: str, base_dir: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    读取文件内容

    Args:
        path: 文件路径
        base_dir: 限制在指定目录下（安全限制）

    Returns:
        {"success": bool, "content": str, "error": str}
    """
    try:
        file_path = Path(path).resolve()

        # 安全检查：如果是相对路径，必须在 base_dir 下
        # 如果是绝对路径，只检查是否真实存在
        if base_dir and not Path(path).is_absolute():
            base = Path(base_dir).resolve()
            file_path = (base / file_path).resolve()
            if not str(file_path).startswith(str(base)):
                return {
                    "success": False,
                    "content": "",
                    "error": f"路径越界: {path}",
                }

        # 检查文件是否存在
        if not file_path.exists():
            return {
                "success": False,
                "content": "",
                "error": f"文件不存在: {path}",
            }

        # 检查是否是文件
        if not file_path.is_file():
            return {
                "success": False,
                "content": "",
                "error": f"不是文件: {path}",
            }

        # 读取内容（限制大小）
        content = file_path.read_text(encoding="utf-8")
        if len(content) > 500_000:  # 500KB
            content = content[:500_000] + "\n\n...(文件过大，已截断)"

        return {
            "success": True,
            "content": content,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "error": str(e),
        }


# ── File Write ───────────────────────────────────────────────────────────────

def file_write(path: str, content: str, **kwargs) -> Dict[str, Any]:
    """
    写入文件内容

    Args:
        path: 文件路径
        content: 内容

    Returns:
        {"success": bool, "path": str, "error": str}
    """
    try:
        file_path = Path(path)

        # 自动创建父目录
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 限制文件大小
        if len(content) > 1_000_000:  # 1MB
            return {
                "success": False,
                "path": str(file_path),
                "error": "文件过大 (>1MB)",
            }

        file_path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(file_path),
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "path": str(file_path),
            "error": str(e),
        }


# ── Glob ─────────────────────────────────────────────────────────────────────

def glob_search(pattern: str, base_dir: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    搜索文件

    Args:
        pattern: 搜索模式 (e.g., "*.py", "**/*.ts")
        base_dir: 限制在指定目录下

    Returns:
        {"success": bool, "files": List[str], "error": str}
    """
    try:
        base = Path(base_dir or "/tmp").resolve()

        # 限制搜索深度
        if "**" in pattern:
            pattern = pattern.replace("**", "*", 1)  # 只允许一层递归

        # 执行搜索
        matches = list(base.glob(pattern))

        # 限制结果数量
        if len(matches) > 100:
            matches = matches[:100]

        files = [str(m.relative_to(base)) for m in matches if m.is_file()]

        return {
            "success": True,
            "files": files,
            "count": len(files),
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "error": str(e),
        }


# ── Web Read ─────────────────────────────────────────────────────────────────

def web_read(url: str, max_length: int = 50000, **kwargs) -> Dict[str, Any]:
    """
    读取网页内容

    Args:
        url: 网页 URL
        max_length: 最大内容长度

    Returns:
        {"success": bool, "content": str, "title": str, "error": str}
    """
    try:
        import urllib.request
        import html

        # 设置请求头模拟浏览器
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            }
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                return {
                    "success": False,
                    "content": "",
                    "title": "",
                    "error": f"不是 HTML 内容: {content_type}",
                }

            html_content = response.read().decode('utf-8', errors='ignore')

        # 简单提取 title
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE)
        title = html.unescape(title_match.group(1).strip()) if title_match else ""

        # 简单提取正文（移除脚本、样式、注释）
        # 移除 <script> 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        # 移除 <style> 标签
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 解码 HTML 实体
        text = html.unescape(text)
        # 合并空白字符
        text = re.sub(r'\s+', ' ', text).strip()

        # 截断
        if len(text) > max_length:
            text = text[:max_length] + "\n\n...(内容过长，已截断)"

        return {
            "success": True,
            "content": text,
            "title": title,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "title": "",
            "error": str(e),
        }


# ── PDF Read ─────────────────────────────────────────────────────────────────

def pdf_read(url: str, max_pages: int = 10, max_length: int = 50000, **kwargs) -> Dict[str, Any]:
    """
    读取 PDF 内容（从 URL 下载）

    Args:
        url: PDF URL
        max_pages: 最多读取页数（避免过大）
        max_length: 最大内容长度

    Returns:
        {"success": bool, "content": str, "title": str, "pages": int, "error": str}
    """
    """
    读取 PDF 内容（从 URL 下载）

    Args:
        url: PDF URL
        max_pages: 最多读取页数（避免过大）
        max_length: 最大内容长度

    Returns:
        {"success": bool, "content": str, "title": str, "pages": int, "error": str}
    """
    import urllib.request
    import tempfile
    from pypdf import PdfReader

    try:
        # 下载 PDF 到临时文件
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = tmp.name

        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'application/pdf,*/*',
            }
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            with open(tmp_path, 'wb') as f:
                f.write(response.read())

        # 提取文本
        reader = PdfReader(tmp_path)
        total_pages = len(reader.pages)

        text_parts = []
        pages_read = 0

        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            text_parts.append(page.extract_text())
            pages_read += 1

        # 清理临时文件
        import os
        os.unlink(tmp_path)

        # 合并文本
        full_text = '\n\n'.join(text_parts)

        # 清理空白
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        # 截断
        if len(full_text) > max_length:
            full_text = full_text[:max_length] + "\n\n...(PDF 内容过长，已截断)"

        return {
            "success": True,
            "content": full_text,
            "title": f"PDF ({pages_read}/{total_pages} 页)",
            "pages": pages_read,
            "total_pages": total_pages,
            "error": "",
        }

    except Exception as e:
        # 清理临时文件
        try:
            import os
            os.unlink(tmp_path)
        except:
            pass
        return {
            "success": False,
            "content": "",
            "title": "",
            "pages": 0,
            "total_pages": 0,
            "error": str(e),
        }


# ── 工具注册表 ────────────────────────────────────────────────────────────────

EXEC_TOOLS = {
    "bash": {
        "func": bash,
        "description": "Execute bash command in sandbox. Returns stdout/stderr.",
        "parameters": {
            "command": "str - bash command to execute",
            "timeout": "int - timeout in seconds (default 30, max 120)",
        },
    },
    "file_read": {
        "func": file_read,
        "description": "Read file contents. Path is relative to work_dir.",
        "parameters": {
            "path": "str - file path",
        },
    },
    "file_write": {
        "func": file_write,
        "description": "Write content to file. Creates parent dirs if needed.",
        "parameters": {
            "path": "str - file path",
            "content": "str - content to write",
        },
    },
    "glob": {
        "func": glob_search,
        "description": "Search for files matching pattern.",
        "parameters": {
            "pattern": "str - glob pattern (e.g., *.py, **/*.ts)",
        },
    },
    "web_read": {
        "func": web_read,
        "description": "Read webpage content from URL. Returns title and text content.",
        "parameters": {
            "url": "str - webpage URL to fetch",
        },
    },
    "pdf_read": {
        "func": pdf_read,
        "description": "Read PDF content from URL. Extracts text from PDF file.",
        "parameters": {
            "url": "str - PDF URL to fetch and parse",
        },
    },
}
