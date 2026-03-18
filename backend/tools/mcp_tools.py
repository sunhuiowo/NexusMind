"""
tools/mcp_tools.py
MCP Tool Server 工具注册
Agent 间通过此标准工具接口通信（原则 3）
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import Memory, RawContent, QueryResult, MemoryCard
from memory.memory_store import get_memory_store
from memory.importance_scorer import mark_important

logger = logging.getLogger(__name__)


def _get_embedder():
    """懒加载 Embedding 函数"""
    from tools.llm import get_embedder
    return get_embedder()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MCP 工具函数（原则 3：Agent 间通信的唯一接口）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def search_memory(
    query: str,
    top_k: int = None,
    min_importance: float = 0.0,
    platform_filter: str = None,
    media_type: str = None,
    use_hybrid: bool = True,  # 是否使用混合检索
) -> QueryResult:
    """
    语义检索记忆（支持混合检索：向量+关键词）
    MCP Tool: search_memory
    """
    top_k = top_k or config.TOP_K_RESULTS
    store = get_memory_store()
    embedder = _get_embedder()

    try:
        query_embedding = embedder.embed(query)
    except Exception as e:
        logger.error(f"[MCP] query embedding 失败: {e}")
        return QueryResult(
            hits=[], overall_summary="检索失败，请检查 Embedding 配置",
            total_found=0, query_intent="search",
        )

    results = store.search_by_vector(
        query_embedding,
        query_text=query,  # 传入原始查询文本用于关键词匹配
        top_k=top_k,
        platform_filter=platform_filter,
        media_type_filter=media_type,
        min_importance=min_importance,
        use_hybrid=use_hybrid,
    )

    # 更新查询计数
    for memory, _ in results:
        store.increment_query_count(memory.id)

    hits = [
        MemoryCard.from_memory(memory, relevance_score=score)
        for memory, score in results
    ]

    return QueryResult(
        hits=hits,
        overall_summary="",  # 由 Knowledge Agent 生成
        total_found=len(hits),
        query_intent="search",
    )


def get_recent(
    days: int = 7,
    platform: str = None,
    media_type: str = None,
    limit: int = None,
) -> QueryResult:
    """
    时间查询：最近 N 天的收藏
    MCP Tool: get_recent
    """
    limit = limit or config.TOP_K_RESULTS
    store = get_memory_store()

    memories = store.search_by_time(
        days=days,
        platform=platform,
        media_type=media_type,
        limit=limit,
    )

    hits = [MemoryCard.from_memory(m) for m in memories]

    time_range = f"最近 {days} 天"
    if platform:
        time_range += f" · {platform}"

    return QueryResult(
        hits=hits,
        overall_summary="",
        total_found=len(hits),
        query_intent="recent",
        time_range=time_range,
    )


def add_memory(raw_content: RawContent, llm_func=None) -> Optional[str]:
    """
    新增记忆入库
    MCP Tool: add_memory
    返回入库的 memory_id，已存在返回 None
    """
    from tools.memory_builder import build_memory_from_content
    store = get_memory_store()
    embedder = _get_embedder()

    memory = build_memory_from_content(raw_content, llm_func=llm_func)
    if not memory:
        return None

    # 生成 embedding（基于 summary，原则 2）
    if memory.summary:
        try:
            memory.embedding = embedder.embed(memory.summary)
        except Exception as e:
            logger.warning(f"[MCP] Embedding 生成失败: {e}")

    success = store.add(memory)
    return memory.id if success else None


def add_memories_batch(
    raw_contents: List[RawContent],
    llm_func=None,
    max_workers: int = 4,
) -> List[Optional[str]]:
    """
    批量新增记忆入库（并行 + 批量 embedding）
    相比逐条调用快 3-5x

    Args:
        raw_contents: 内容列表
        llm_func: LLM 调用函数
        max_workers: 并行处理的线程数

    Returns:
        memory_id 列表
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tools.memory_builder import build_memory_from_content

    if not raw_contents:
        return []

    store = get_memory_store()
    embedder = _get_embedder()

    # 并行构建 memory 对象
    memories = []
    logger.info(f"[MCP] 批量入库：并行构建 {len(raw_contents)} 条记忆...")

    def build_single(content: RawContent) -> Optional[Memory]:
        try:
            return build_memory_from_content(content, llm_func=llm_func)
        except Exception as e:
            logger.warning(f"[MCP] 构建 memory 失败: {e}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(build_single, c): c for c in raw_contents}
        for future in as_completed(futures):
            memory = future.result()
            if memory:
                memories.append(memory)

    if not memories:
        return []

    logger.info(f"[MCP] 批量入库：完成构建 {len(memories)} 条，开始批量 embedding...")

    # 批量生成 embedding
    summaries = [m.summary for m in memories if m.summary]
    summary_to_memory = {m.summary: m for m in memories if m.summary}

    if summaries:
        try:
            embeddings = embedder.embed_batch(summaries)
            for summary, embedding in zip(summaries, embeddings):
                if summary in summary_to_memory:
                    summary_to_memory[summary].embedding = embedding
        except Exception as e:
            logger.warning(f"[MCP] 批量 embedding 生成失败，回退逐条: {e}")
            for m in memories:
                if m.summary:
                    try:
                        m.embedding = embedder.embed(m.summary)
                    except:
                        pass

    # 批量写入存储
    logger.info(f"[MCP] 批量入库：写入 {len(memories)} 条到存储...")
    results = store.add_batch(memories)
    memory_ids = [memories[i].id if results[i] else None for i in range(len(memories))]

    added = sum(1 for m in memory_ids if m)
    logger.info(f"[MCP] 批量入库完成：成功 {added}/{len(memories)} 条")

    return memory_ids


def update_importance(
    memory_id: str,
    delta: float = None,
    set_value: float = None,
) -> bool:
    """
    更新记忆重要性
    MCP Tool: update_importance
    delta: 增减量（+/-）
    set_value: 直接设置值
    """
    store = get_memory_store()
    memory = store.get(memory_id)
    if not memory:
        return False

    if set_value is not None:
        memory.importance = max(0.0, min(1.0, set_value))
    elif delta is not None:
        memory.importance = max(0.0, min(1.0, memory.importance + delta))

    memory.last_accessed_at = datetime.utcnow().isoformat()
    return store.update(memory)


def find_related(memory_id: str, top_k: int = 5) -> QueryResult:
    """
    查找关联记忆
    MCP Tool: find_related
    """
    store = get_memory_store()
    embedder = _get_embedder()

    source = store.get(memory_id)
    if not source:
        return QueryResult(hits=[], total_found=0, query_intent="related")

    # 先用 related_ids 快速返回
    related = []
    for rid in source.related_ids[:top_k]:
        m = store.get(rid)
        if m:
            related.append((m, 0.9))

    # 不足则向量扩散
    if len(related) < top_k and source.summary:
        try:
            embedding = embedder.embed(source.summary)
            vector_results = store.search_by_vector(embedding, top_k=top_k + 5)
            for m, score in vector_results:
                if m.id != memory_id and not any(r.id == m.id for r, _ in related):
                    related.append((m, score))
                if len(related) >= top_k:
                    break
        except Exception:
            pass

    hits = [MemoryCard.from_memory(m, score) for m, score in related[:top_k]]
    return QueryResult(hits=hits, total_found=len(hits), query_intent="related")


def summarize_memories(memory_ids: List[str], llm_func=None) -> str:
    """
    批量总结多条记忆
    MCP Tool: summarize_memories
    """
    store = get_memory_store()
    memories = [store.get(mid) for mid in memory_ids if mid]
    memories = [m for m in memories if m]

    if not memories:
        return "未找到相关记忆"

    summaries = "\n\n".join([
        f"【{m.platform_name}】{m.title}：{m.summary}"
        for m in memories
    ])

    if llm_func:
        try:
            return llm_func(
                f"请综合总结以下 {len(memories)} 条收藏内容的核心主题和关联：\n\n{summaries[:4000]}"
            )
        except Exception:
            pass

    return summaries[:500]


def get_by_platform(
    platform: str,
    topic_query: str = None,
    limit: int = None,
) -> QueryResult:
    """
    按平台过滤查询
    MCP Tool: get_by_platform
    """
    limit = limit or config.TOP_K_RESULTS
    store = get_memory_store()
    embedder = _get_embedder()

    topic_ids = None
    if topic_query:
        try:
            embedding = embedder.embed(topic_query)
            results = store.search_by_vector(embedding, top_k=limit * 2, platform_filter=platform)
            topic_ids = [m.id for m, _ in results]
        except Exception:
            pass

    memories = store.search_by_platform(platform, topic_query_ids=topic_ids, limit=limit)
    hits = [MemoryCard.from_memory(m) for m in memories]

    return QueryResult(
        hits=hits,
        total_found=len(hits),
        query_intent="platform",
    )


def get_by_tags(
    tags: List[str],
    match_mode: str = "any",  # any / all
) -> QueryResult:
    """
    按标签过滤
    MCP Tool: get_by_tags
    """
    store = get_memory_store()
    memories = store.search_by_tags(tags, match_mode=match_mode)
    hits = [MemoryCard.from_memory(m) for m in memories]

    return QueryResult(hits=hits, total_found=len(hits), query_intent="search")


def delete_memory(memory_id: str) -> bool:
    """
    删除记忆
    MCP Tool: delete_memory
    """
    store = get_memory_store()
    return store.delete(memory_id)


def get_stats(platform_filter: str = None) -> Dict[str, Any]:
    """
    统计信息
    MCP Tool: get_stats
    """
    store = get_memory_store()
    return store.get_stats(platform_filter=platform_filter)


def sync_platform(platform: str, full_sync: bool = False) -> Dict[str, Any]:
    """
    触发平台同步
    MCP Tool: sync_platform
    委托给 CollectorAgent 执行
    """
    from agents.collector_agent import CollectorAgent
    agent = CollectorAgent()
    return agent.sync_single_platform(platform, full_sync=full_sync)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MCP 工具注册表（供 LangChain / LangGraph 使用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MCP_TOOL_REGISTRY = {
    "search_memory": {
        "func": search_memory,
        "description": "混合检索记忆库（语义向量+关键词匹配），支持平台和媒体类型过滤",
        "parameters": {
            "query": "str - 检索关键词或问题",
            "top_k": "int - 最大返回数（默认 5）",
            "min_importance": "float - 最低重要性阈值（0.0~1.0）",
            "platform_filter": "str - 平台过滤（如 youtube）",
            "media_type": "str - 媒体类型过滤（text/video/audio/image/repo/pdf）",
            "use_hybrid": "bool - 是否使用混合检索（默认 True）",
        },
    },
    "get_recent": {
        "func": get_recent,
        "description": "按时间查询最近收藏",
        "parameters": {
            "days": "int - 最近 N 天（默认 7）",
            "platform": "str - 平台过滤",
            "media_type": "str - 媒体类型过滤",
            "limit": "int - 返回条数",
        },
    },
    "add_memory": {
        "func": add_memory,
        "description": "新增内容入库",
        "parameters": {"raw_content": "RawContent - 标准化原始内容对象"},
    },
    "update_importance": {
        "func": update_importance,
        "description": "更新记忆重要性分数",
        "parameters": {
            "memory_id": "str - 记忆 ID",
            "delta": "float - 增减量",
            "set_value": "float - 直接设置值",
        },
    },
    "find_related": {
        "func": find_related,
        "description": "查找与指定记忆关联的其他记忆",
        "parameters": {"memory_id": "str", "top_k": "int"},
    },
    "summarize_memories": {
        "func": summarize_memories,
        "description": "批量总结多条记忆",
        "parameters": {"memory_ids": "List[str]"},
    },
    "get_by_platform": {
        "func": get_by_platform,
        "description": "按平台过滤查询",
        "parameters": {"platform": "str", "topic_query": "str", "limit": "int"},
    },
    "get_by_tags": {
        "func": get_by_tags,
        "description": "按标签过滤",
        "parameters": {"tags": "List[str]", "match_mode": "any|all"},
    },
    "delete_memory": {
        "func": delete_memory,
        "description": "删除记忆",
        "parameters": {"memory_id": "str"},
    },
    "get_stats": {
        "func": get_stats,
        "description": "获取统计信息",
        "parameters": {"platform_filter": "str（可选）"},
    },
    "sync_platform": {
        "func": sync_platform,
        "description": "触发平台同步",
        "parameters": {"platform": "str", "full_sync": "bool"},
    },
}
