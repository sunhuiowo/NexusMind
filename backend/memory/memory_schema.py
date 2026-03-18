"""
memory_schema.py
核心数据结构定义 - Memory / RawContent / QueryResult / MemoryCard
原则：字段只增不改，保持向后兼容
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid


# ──────────────────────────────────────────────────────────────────────────────
# 原始内容：平台 normalize() 后的统一对象
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RawBookmark:
    """平台侧原始书签/收藏条目，用于增量同步"""
    platform: str
    platform_id: str
    url: str
    title: str
    bookmarked_at: datetime
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RawContent:
    """平台 normalize() 后的统一原始内容对象"""
    # 平台信息
    platform: str            # 平台 ID，如 'youtube'
    platform_name: str       # 平台显示名，如 'YouTube'
    platform_id: str         # 平台侧原始内容 ID
    url: str                 # 内容原始链接
    title: str               # 标题
    body: str                # 正文 / 描述 / 转录文本
    media_type: str          # text/video/audio/image/repo/pdf
    author: str              # 作者 / UP主 / 账号名
    thumbnail_url: str = ""  # 封面图链接
    bookmarked_at: Optional[datetime] = None  # 用户收藏时间
    raw_metadata: Dict[str, Any] = field(default_factory=dict)  # 平台原始字段备用


# ──────────────────────────────────────────────────────────────────────────────
# 结构化记忆对象
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Memory:
    """
    结构化记忆对象 - 系统核心数据单元
    所有字段在入库时一次性写入，问答时无需二次查询
    """
    # ── 唯一标识 ──────────────────────────────────────────────────────────────
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # ── 平台来源（问答必须返回的核心字段）────────────────────────────────────
    platform: str = ""           # 平台 ID：'youtube' / 'xiaohongshu' ...
    platform_name: str = ""      # 平台显示名：'YouTube' / '小红书' ...
    platform_id: str = ""        # 平台侧原始内容 ID
    source_url: str = ""         # 内容原始链接
    author: str = ""             # 作者 / UP主 / 账号名
    bookmarked_at: str = ""      # 用户收藏时间（非入库时间）ISO 8601

    # ── 内容 ──────────────────────────────────────────────────────────────────
    title: str = ""              # 收藏内容名称
    summary: str = ""            # LLM 生成摘要，100字以内
    raw_content: str = ""        # 原始全文，备用，不做 Embedding
    tags: List[str] = field(default_factory=list)  # 自动打标，3-5个关键词
    media_type: str = ""         # text/video/audio/image/repo/pdf
    thumbnail_url: str = ""      # 封面图链接，展示用

    # ── 向量 ──────────────────────────────────────────────────────────────────
    embedding: List[float] = field(default_factory=list)  # 基于 summary 生成

    # ── 重要性 ────────────────────────────────────────────────────────────────
    importance: float = 0.5      # 0.0 ~ 1.0，动态更新
    query_count: int = 0         # 被检索命中次数
    last_accessed_at: str = ""   # 最后被访问时间，用于时间衰减

    # ── 关联 ──────────────────────────────────────────────────────────────────
    related_ids: List[str] = field(default_factory=list)  # 语义相关的其他记忆 ID
    parent_id: Optional[str] = None  # 子记忆指向主记忆 ID（视频分段用）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "platform": self.platform,
            "platform_name": self.platform_name,
            "platform_id": self.platform_id,
            "source_url": self.source_url,
            "author": self.author,
            "bookmarked_at": self.bookmarked_at,
            "title": self.title,
            "summary": self.summary,
            "raw_content": self.raw_content,
            "tags": self.tags,
            "media_type": self.media_type,
            "thumbnail_url": self.thumbnail_url,
            "embedding": self.embedding,
            "importance": self.importance,
            "query_count": self.query_count,
            "last_accessed_at": self.last_accessed_at,
            "related_ids": self.related_ids,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Memory":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            created_at=d.get("created_at", ""),
            platform=d.get("platform", ""),
            platform_name=d.get("platform_name", ""),
            platform_id=d.get("platform_id", ""),
            source_url=d.get("source_url", ""),
            author=d.get("author", ""),
            bookmarked_at=d.get("bookmarked_at", ""),
            title=d.get("title", ""),
            summary=d.get("summary", ""),
            raw_content=d.get("raw_content", ""),
            tags=d.get("tags", []),
            media_type=d.get("media_type", ""),
            thumbnail_url=d.get("thumbnail_url", ""),
            embedding=d.get("embedding", []),
            importance=d.get("importance", 0.5),
            query_count=d.get("query_count", 0),
            last_accessed_at=d.get("last_accessed_at", ""),
            related_ids=d.get("related_ids", []),
            parent_id=d.get("parent_id", None),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 问答输出结构
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryCard:
    """
    单条命中记忆的结构化卡片
    platform_name / title / summary / bookmarked_at / source_url 为必填字段
    """
    # ── 必须返回字段 ──────────────────────────────────────────────────────────
    platform_name: str           # 平台显示名称，如 'YouTube' / '小红书'
    title: str                   # 收藏内容名称
    summary: str                 # 收藏内容摘要，2-3句话
    bookmarked_at: str           # 收藏时间，格式 'YYYY-MM-DD'
    source_url: str              # 原始链接

    # ── 扩展字段（按需展示）──────────────────────────────────────────────────
    author: str = ""             # 作者
    media_type: str = ""         # 内容类型
    tags: List[str] = field(default_factory=list)  # 标签
    importance: float = 0.5     # 重要性分数
    relevance_score: float = 0.0  # 本次查询相关度
    thumbnail_url: str = ""      # 封面图
    memory_id: str = ""          # 原始 Memory ID

    @classmethod
    def from_memory(cls, memory: Memory, relevance_score: float = 0.0) -> "MemoryCard":
        """从 Memory 对象生成 MemoryCard"""
        # 格式化收藏时间
        bookmarked_at = memory.bookmarked_at
        if bookmarked_at and "T" in bookmarked_at:
            bookmarked_at = bookmarked_at.split("T")[0]

        return cls(
            platform_name=memory.platform_name,
            title=memory.title,
            summary=memory.summary,
            bookmarked_at=bookmarked_at,
            source_url=memory.source_url,
            author=memory.author,
            media_type=memory.media_type,
            tags=memory.tags,
            importance=memory.importance,
            relevance_score=relevance_score,
            thumbnail_url=memory.thumbnail_url,
            memory_id=memory.id,
        )

    def format_display(self, index: int) -> str:
        """格式化为可读展示文本"""
        media_label = {
            "video": "视频", "audio": "音频", "image": "图文",
            "text": "文章", "repo": "代码仓库", "pdf": "PDF"
        }.get(self.media_type, self.media_type)

        lines = [
            f"{'①②③④⑤⑥⑦⑧⑨⑩'[min(index, 9)]} {self.title}",
            f"   平台：{self.platform_name}",
        ]
        if self.author:
            lines.append(f"   作者：{self.author}")
        lines.append(f"   收藏于：{self.bookmarked_at} · 类型：{media_label}")
        if self.summary:
            lines.append(f"   摘要：{self.summary}")
        if self.tags:
            lines.append(f"   标签：{' / '.join(self.tags)}")
        lines.append(f"   链接：{self.source_url}")
        return "\n".join(lines)


@dataclass
class QueryResult:
    """
    Knowledge Agent 所有查询的标准化输出结构
    无论何种意图，都必须返回此对象
    """
    hits: List[MemoryCard] = field(default_factory=list)   # 命中记忆卡片列表
    overall_summary: str = ""                               # 综合总结
    total_found: int = 0                                    # 命中总数
    query_intent: str = "search"                            # search/recent/summary/platform/complex
    time_range: str = ""                                    # 时间过滤说明
    thinking: str = ""                                      # AI 思考过程

    def format_display(self) -> str:
        """格式化为用户可见的标准问答输出"""
        lines = ["━" * 40]

        if self.time_range:
            lines.append(f"找到 {self.total_found} 条相关收藏（{self.time_range}）：")
        else:
            lines.append(f"找到 {self.total_found} 条相关收藏：")

        lines.append("")

        for i, card in enumerate(self.hits):
            lines.append(card.format_display(i))
            lines.append("")

        if self.overall_summary:
            lines.append("━" * 40)
            lines.append("综合总结：")
            lines.append(self.overall_summary)

        lines.append("━" * 40)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": [
                {
                    "platform_name": c.platform_name,
                    "title": c.title,
                    "summary": c.summary,
                    "bookmarked_at": c.bookmarked_at,
                    "source_url": c.source_url,
                    "author": c.author,
                    "media_type": c.media_type,
                    "tags": c.tags,
                    "importance": c.importance,
                    "relevance_score": c.relevance_score,
                    "thumbnail_url": c.thumbnail_url,
                    "memory_id": c.memory_id,
                }
                for c in self.hits
            ],
            "overall_summary": self.overall_summary,
            "total_found": self.total_found,
            "query_intent": self.query_intent,
            "time_range": self.time_range,
            "thinking": self.thinking,
        }
