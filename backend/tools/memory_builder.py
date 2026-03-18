"""
tools/memory_builder.py
RawContent -> Memory 转换
LLM 生成 summary + tags，重要性评分
"""

import re
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.memory_schema import Memory, RawContent
from memory.importance_scorer import llm_initial_score

logger = logging.getLogger(__name__)


def _generate_all_in_one(content: RawContent, llm_func=None) -> tuple:
    """
    一次性生成 summary + tags + importance
    减少 LLM 调用次数：3次 -> 1次

    Returns:
        (summary: str, tags: List[str], importance: float)
    """
    source_text = content.body or content.title or ""
    clean_text = _clean_html(source_text)
    if not clean_text:
        clean_text = content.title or ""

    # 基础提取
    base_summary = _extract_key_sentences(clean_text, max_sentences=3)

    if not llm_func:
        # 无 LLM 时使用降级策略
        return base_summary[:200] if base_summary else clean_text[:150], [], 0.5

    # 合并 prompt：一次调用获取所有
    prompt = f"""请分析以下内容，一次性完成三个任务：

1. 摘要：用80字以内概括核心内容
2. 标签：提取3-5个关键词标签（用逗号分隔）
3. 评分：评估知识价值0.0-1.0（0.3以下碎片信息，0.3-0.6一般，0.6-0.8有深度，0.8-1.0核心参考）

标题：{content.title}
类型：{content.media_type}
内容：{base_summary[:500]}

请按以下格式返回（每行一个任务）：
[摘要]{{你的摘要}}
[标签]{{tag1,tag2,tag3}}
[评分]{{0.0-1.0的小数}}"""

    try:
        result = llm_func(prompt, max_tokens=300)
        if not result:
            raise ValueError("LLM 返回为空")

        # 解析结果
        summary = ""
        tags = []
        importance = 0.5

        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("[摘要]"):
                summary = line[3:].strip()
            elif line.startswith("[标签]"):
                tag_str = line[3:].strip()
                tags = [t.strip().lower() for t in tag_str.split(",") if t.strip()][:5]
            elif line.startswith("[评分]"):
                try:
                    importance = float(line[3:].strip())
                    importance = max(0.0, min(1.0, importance))
                except:
                    pass

        if summary and len(summary) > 5:
            return summary[:200], tags, importance
        else:
            raise ValueError("摘要解析失败")

    except Exception as e:
        logger.debug(f"[MemoryBuilder] 合并生成失败，回退分段: {e}")
        # 回退：分别调用
        summary = _generate_summary(content, llm_func)
        tags = _generate_tags(content, llm_func)
        importance = 0.5
        return summary, tags, importance


def _clean_html(html_text: str) -> str:
    """清理HTML标签，提取纯文本"""
    if not html_text:
        return ""

    # 移除 script 和 style 标签及其内容
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # 移除 HTML 注释
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # 替换常见 HTML 标签为换行或空格
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<div[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)

    # 移除所有其他 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)

    # 解码 HTML 实体
    import html
    text = html.unescape(text)

    # 清理多余空白
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()

    return text


def _extract_key_sentences(text: str, max_sentences: int = 3) -> str:
    """从文本中提取关键句子作为摘要"""
    if not text:
        return ""

    # 按句子分割（支持中英文句号、问号、感叹号）
    sentences = re.split(r'[。！？.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return text[:150]

    # 简单的关键词权重评分
    def score_sentence(sentence: str) -> int:
        score = 0
        # 长度适中（20-100字符）加分
        length = len(sentence)
        if 20 <= length <= 100:
            score += 10
        # 包含技术关键词加分
        tech_keywords = ['api', '框架', '工具', '库', '算法', '模型', '数据', '代码', '开发', '实现', 'python', 'javascript', 'github']
        for kw in tech_keywords:
            if kw.lower() in sentence.lower():
                score += 5
        # 包含数字加分（可能是版本号、统计数据等）
        if re.search(r'\d+', sentence):
            score += 3
        # 开头是"介绍"、"简介"等加分
        if re.match(r'^(介绍|简介|概述|什么是|本文)', sentence):
            score += 5
        return score

    # 按分数排序，取前 N 句
    scored = [(s, score_sentence(s)) for s in sentences]
    scored.sort(key=lambda x: -x[1])

    selected = scored[:max_sentences]
    # 按原文顺序排列
    selected.sort(key=lambda x: sentences.index(x[0]))

    summary = '。'.join([s[0] for s in selected]) + '。'
    return summary[:300]


def _generate_summary(content: RawContent, llm_func=None) -> str:
    """
    生成高质量摘要
    流程：清理HTML -> 提取关键句子 -> LLM优化（可选）
    """
    source_text = content.body or content.title
    if not source_text:
        return content.title or ""

    # 步骤1: 清理HTML
    clean_text = _clean_html(source_text)
    if not clean_text:
        clean_text = content.title or ""

    # 步骤2: 提取关键句子作为基础摘要
    base_summary = _extract_key_sentences(clean_text, max_sentences=3)

    # 步骤3: 如果有LLM，进一步优化摘要
    if llm_func and len(clean_text) > 50:
        prompt = f"""请基于以下关键信息，用80字以内生成一个简洁准确的摘要。
突出核心主题和用途：

标题：{content.title}
关键内容：{base_summary}

只返回摘要文本，不要其他内容："""
        try:
            llm_summary = llm_func(prompt, max_tokens=120)
            if llm_summary and len(llm_summary) > 10:
                return llm_summary[:200]
        except Exception as e:
            logger.debug(f"[MemoryBuilder] LLM 摘要优化失败: {e}")

    # 降级：使用提取的关键句子
    if base_summary:
        return base_summary

    # 最终降级：清理后的前150字
    return clean_text[:150] + ("..." if len(clean_text) > 150 else "")


def _generate_tags(content: RawContent, llm_func=None) -> List[str]:
    """
    生成高质量标签
    结合标题、清理后的内容和平台信息
    """
    # 清理内容用于标签提取
    clean_body = _clean_html(content.body or "")[:1000]

    # 构建标签提取的源文本
    source_text = f"标题：{content.title}\n内容：{clean_body}"

    if llm_func:
        prompt = f"""为以下内容提取 3-5 个关键词标签，要求：
1. 标签应该准确反映内容主题
2. 可以包含技术栈、领域、类型等
3. 用逗号分隔
4. 优先使用英文技术术语

{source_text}

只返回标签，用逗号分隔，不要其他内容（示例：machine-learning, Python, API, 开源工具）："""
        try:
            result = llm_func(prompt, max_tokens=60)
            if result:
                tags = [t.strip().lower() for t in result.split(",") if t.strip()]
                # 过滤太短的标签
                tags = [t for t in tags if len(t) >= 2]
                if tags:
                    return tags[:5]
        except Exception as e:
            logger.debug(f"[MemoryBuilder] LLM 标签生成失败: {e}")

    # 降级策略：从标题和清理后的内容提取关键词
    tags = []

    # 从标题提取
    title_words = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}', content.title or "")
    tags.extend([w.lower() for w in title_words if len(w) >= 2])

    # 技术关键词匹配
    tech_patterns = [
        (r'\b(python|javascript|typescript|java|go|rust|cpp|c\+\+)\b', 'programming'),
        (r'\b(machine learning|ml|ai|deep learning|nlp|cv)\b', 'ai-ml'),
        (r'\b(api|rest|graphql|grpc)\b', 'api'),
        (r'\b(framework|library|tool)\b', 'tools'),
        (r'\b(database|sql|nosql|redis|mongodb)\b', 'database'),
        (r'\b(frontend|backend|fullstack|web)\b', 'web-dev'),
        (r'\b(github|gitlab|opensource)\b', 'open-source'),
    ]

    text_to_search = f"{content.title} {clean_body}".lower()
    for pattern, tag in tech_patterns:
        if re.search(pattern, text_to_search, re.IGNORECASE):
            tags.append(tag)

    # 去重并限制数量
    unique_tags = list(dict.fromkeys(tags))
    return unique_tags[:5]


def build_memory_from_content(
    raw_content: RawContent,
    llm_func=None,
) -> Optional[Memory]:
    """
    将 RawContent 转化为结构化 Memory 对象
    包含：LLM 摘要生成、自动打标、重要性初始评分
    """
    if not raw_content:
        return None

    # 一次性生成 summary + tags + importance（3次 LLM -> 1次）
    summary, tags, importance = _generate_all_in_one(raw_content, llm_func)

    # 收藏时间格式化
    bookmarked_at = ""
    if raw_content.bookmarked_at:
        if isinstance(raw_content.bookmarked_at, datetime):
            bookmarked_at = raw_content.bookmarked_at.isoformat()
        else:
            bookmarked_at = str(raw_content.bookmarked_at)

    memory = Memory(
        platform=raw_content.platform,
        platform_name=raw_content.platform_name,
        platform_id=raw_content.platform_id,
        source_url=raw_content.url,
        author=raw_content.author,
        bookmarked_at=bookmarked_at,
        title=raw_content.title,
        summary=summary,
        raw_content=raw_content.body,
        tags=tags,
        media_type=raw_content.media_type,
        thumbnail_url=raw_content.thumbnail_url,
        importance=importance,
        last_accessed_at=datetime.utcnow().isoformat(),
    )

    return memory
