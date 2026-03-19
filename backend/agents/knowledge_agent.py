"""
agents/knowledge_agent.py
Knowledge Agent - 意图解析 + 问答 + 标准化输出
所有输出必须封装为 QueryResult（原则 4）
支持 Plan-and-Execute 复合查询（Phase 4）
"""

import logging
import re
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import QueryResult, MemoryCard
from tools.mcp_tools import (
    search_memory, get_recent, get_by_platform,
    get_by_tags, find_related, summarize_memories,
)
from tools.llm import get_llm_client

logger = logging.getLogger(__name__)


# ── 意图识别 ──────────────────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "recent": [
        r"最近\d*[天周月]", r"今天|昨天|本周|本月",
        r"last\s+\d+\s+days?", r"recently", r"lately",
        r"新增|新收藏",
    ],
    "platform": [
        r"(youtube|bilibili|b站|github|twitter|x|pocket|微信|小红书|抖音).*?(收藏|star|书签)",
        r"在(youtube|bilibili|b站|github|twitter|x|pocket|微信|小红书|抖音)",
        r"(youtube|bilibili|b站|github|twitter|x|pocket|微信|小红书|抖音)上",
    ],
    "summary": [
        r"总结|归纳|汇总|梳理",
        r"summarize|summary|overview",
        r"关于.*?的所有",
    ],
    "related": [
        r"(和|与|跟).*?(相关|类似|关联)",
        r"related to|similar to|like this",
    ],
    "complex": [
        r"按.*?分类|分类.*?总结",
        r"compare|对比.*?分析",
        r".*?和.*?.*?(对比|比较|区别)",
        r"分别.*?总结",
    ],
}

PLATFORM_KEYWORD_MAP = {
    "youtube": "youtube",
    "bilibili": "bilibili",
    "b站": "bilibili",
    "github": "github",
    "twitter": "twitter",
    "x": "twitter",
    "pocket": "pocket",
    "微信": "wechat",
    "小红书": "xiaohongshu",
    "抖音": "douyin",
}


def _detect_intent(query: str) -> Tuple[str, Dict[str, Any]]:
    """
    意图识别
    返回 (intent_type, params)
    """
    query_lower = query.lower()
    params = {}

    # 复合查询优先（最复杂）
    for pattern in INTENT_PATTERNS["complex"]:
        if re.search(pattern, query, re.IGNORECASE):
            return "complex", params

    # 平台过滤
    for kw, platform_id in PLATFORM_KEYWORD_MAP.items():
        if kw in query_lower:
            params["platform"] = platform_id
            break

    for pattern in INTENT_PATTERNS["platform"]:
        if re.search(pattern, query, re.IGNORECASE):
            return "platform", params

    # 主题总结
    for pattern in INTENT_PATTERNS["summary"]:
        if re.search(pattern, query, re.IGNORECASE):
            return "summary", params

    # 时间查询
    for pattern in INTENT_PATTERNS["recent"]:
        if re.search(pattern, query, re.IGNORECASE):
            days = _extract_days(query)
            params["days"] = days
            return "recent", params

    # 关联推荐
    for pattern in INTENT_PATTERNS["related"]:
        if re.search(pattern, query, re.IGNORECASE):
            return "related", params

    # 默认：语义搜索
    return "search", params


def _extract_days(query: str) -> int:
    """从查询中提取时间天数"""
    patterns = [
        (r"(\d+)天", 1),
        (r"(\d+)周", 7),
        (r"(\d+)个?月", 30),
        (r"今天", 1),
        (r"昨天", 2),
        (r"本周|这周", 7),
        (r"本月|这月", 30),
        (r"last\s+(\d+)\s+days?", 1),
        (r"last\s+(\d+)\s+weeks?", 7),
    ]

    for pattern, multiplier in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            try:
                num = int(match.group(1))
                return num * multiplier
            except (IndexError, ValueError):
                return multiplier

    return 7  # 默认 7 天


def _generate_overall_summary(hits: List[MemoryCard], query: str, llm_func=None) -> str:
    """生成回答 - 直接回答用户问题，引用收藏作为参考"""
    if not hits or not llm_func:
        return ""

    # 列出所有收藏的标题，确保 LLM 知道有多少条
    all_titles = "\n".join([
        f"{i+1}. [{c.platform_name}] {c.title}"
        for i, c in enumerate(hits[:8])
    ])

    cards_text = "\n\n".join([
        f"【{c.platform_name}】{c.title}：{c.summary}"
        for c in hits[:8]
    ])

    try:
        return llm_func(
            f"用户问题：{query}\n\n"
            f"以下是找到的 {len(hits)} 条收藏的标题：\n{all_titles}\n\n"
            f"详细内容和摘要：\n{cards_text}\n\n"
            f"重要要求：\n"
            f"1. 必须根据以上所有 {len(hits)} 条收藏来回答问题\n"
            f"2. 回答要简洁、自然，像人与人对话一样\n"
            f"3. 不要只提到一条内容，要综合所有相关的收藏\n"
            f"4. 不需要列出收藏列表，只需在回答中自然引用这些信息：",
            max_tokens=800,
        )
    except Exception:
        return ""


# ── 各意图执行策略 ─────────────────────────────────────────────────────────────

def _execute_search(query: str, params: Dict, user_id: str, llm_func=None) -> QueryResult:
    """语义搜索"""
    result = search_memory(
        query=query,
        user_id=user_id,
        top_k=config.TOP_K_RESULTS,
        platform_filter=params.get("platform"),
    )
    result.query_intent = "search"

    if result.hits:
        if llm_func:
            result.overall_summary = _generate_overall_summary(result.hits, query, llm_func)
        # Fallback: 直接使用第一個收藏的标题作为回答
        if not result.overall_summary:
            result.overall_summary = f"找到 {len(result.hits)} 条相关收藏，详情请查看下方引用。"

    return result


def _execute_recent(query: str, params: Dict, user_id: str, llm_func=None) -> QueryResult:
    """时间查询"""
    days = params.get("days", 7)
    platform = params.get("platform")

    result = get_recent(user_id=user_id, days=days, platform=platform)
    result.query_intent = "recent"
    result.time_range = f"最近 {days} 天"

    if result.hits:
        if llm_func:
            result.overall_summary = _generate_overall_summary(result.hits, query, llm_func)
        if not result.overall_summary:
            result.overall_summary = f"找到 {len(result.hits)} 条最近 {days} 天的收藏，详情请查看下方引用。"

    return result


def _execute_summary(query: str, params: Dict, user_id: str, llm_func=None) -> QueryResult:
    """主题总结：检索 + 分组 + LLM 总结"""
    # 先语义检索，top_k 加大
    result = search_memory(query=query, user_id=user_id, top_k=10)
    result.query_intent = "summary"

    memory_ids = [card.memory_id for card in result.hits if card.memory_id]
    if memory_ids and llm_func:
        result.overall_summary = summarize_memories(user_id=user_id, memory_ids=memory_ids, llm_func=llm_func)

    # Fallback
    if not result.overall_summary and result.hits:
        result.overall_summary = f"找到 {len(result.hits)} 条相关收藏，详情请查看下方引用。"

    return result


def _execute_platform(query: str, params: Dict, user_id: str, llm_func=None) -> QueryResult:
    """平台过滤查询"""
    platform = params.get("platform")
    if not platform:
        return _execute_search(query, params, user_id, llm_func)

    result = get_by_platform(platform=platform, user_id=user_id, topic_query=query)
    result.query_intent = "platform"

    if result.hits:
        if llm_func:
            result.overall_summary = _generate_overall_summary(result.hits, query, llm_func)
        if not result.overall_summary:
            result.overall_summary = f"找到 {len(result.hits)} 条 {platform} 平台的收藏，详情请查看下方引用。"

    return result


def _execute_complex(query: str, params: Dict, user_id: str, llm_func=None) -> QueryResult:
    """
    复合查询 - Plan-and-Execute 架构
    LLM 分解查询 → 多步执行 → 汇总结果
    """
    if not llm_func:
        return _execute_search(query, params, user_id, llm_func)

    # Step 1: LLM 分解查询为子任务
    decompose_prompt = f"""将以下复杂查询分解为 2-4 个简单子查询，每行一个，只返回子查询列表：

复杂查询：{query}

子查询（每行一个）："""

    try:
        sub_queries_text = llm_func(decompose_prompt, max_tokens=200)
        sub_queries = [q.strip() for q in sub_queries_text.strip().split("\n") if q.strip()]
    except Exception:
        sub_queries = [query]

    if not sub_queries:
        sub_queries = [query]

    # Step 2: 执行每个子查询
    all_hits: Dict[str, MemoryCard] = {}  # 去重，memory_id -> MemoryCard

    for sub_q in sub_queries[:4]:  # 最多4个子查询
        try:
            sub_result = search_memory(query=sub_q, user_id=user_id, top_k=5)
            for card in sub_result.hits:
                if card.memory_id and card.memory_id not in all_hits:
                    all_hits[card.memory_id] = card
        except Exception as e:
            logger.debug(f"[KnowledgeAgent] 子查询失败 '{sub_q}': {e}")

    # Step 3: 汇总排序（按 relevance_score 降序）
    sorted_hits = sorted(all_hits.values(), key=lambda c: c.relevance_score, reverse=True)

    # Step 4: LLM 生成回答
    overall_summary = ""
    if sorted_hits and llm_func:
        cards_text = "\n\n".join([
            f"【{c.platform_name}】{c.title}：{c.summary}"
            for c in sorted_hits[:8]
        ])
        try:
            overall_summary = llm_func(
                f"用户问题：{query}\n\n"
                f"参考收藏：\n{cards_text}\n\n"
                f"请直接回答用户的问题。回答要简洁，自然，像人与人对话一样。\n"
                f"如果需要，可以引用收藏中的具体信息作为回答的依据：",
                max_tokens=500,
            )
        except Exception:
            pass

    # Fallback
    if not overall_summary and sorted_hits:
        overall_summary = f"找到 {len(sorted_hits)} 条相关收藏，详情请查看下方引用。"

    return QueryResult(
        hits=sorted_hits[:config.TOP_K_RESULTS],
        overall_summary=overall_summary,
        total_found=len(sorted_hits),
        query_intent="complex",
    )


# ── Knowledge Agent 主入口 ─────────────────────────────────────────────────────

class KnowledgeAgent:
    """
    Knowledge Agent
    职责：意图解析 + 问答路由 + 标准化 QueryResult 输出
    原则 4：所有输出必须封装为 QueryResult，MemoryCard 五个必填字段不可缺
    """

    def __init__(self, user_id: str = None):
        self._llm = get_llm_client()
        self._user_id = user_id

    def query(self, user_query: str, user_id: str, conversation_history: Optional[List[dict]] = None) -> QueryResult:
        """
        主查询入口
        无论何种意图，都返回 QueryResult（原则 4）
        """
        self._user_id = user_id
        if not user_query or not user_query.strip():
            return QueryResult(
                hits=[],
                overall_summary="请输入查询内容",
                total_found=0,
                query_intent="search",
            )

        # 构建带上下文的查询
        context_prefix = ""
        if conversation_history and len(conversation_history) > 0:
            history_text = "\n".join([
                f"{'用户' if h.get('role') == 'user' else '助手'}: {h.get('content', '')[:200]}"
                for h in conversation_history[-5:]  # 最近5轮
            ])
            context_prefix = f"对话历史:\n{history_text}\n\n当前问题: {user_query}"
            enhanced_query = context_prefix
        else:
            enhanced_query = user_query

        intent, params = _detect_intent(user_query)
        logger.info(f"[KnowledgeAgent] 意图: {intent}, 参数: {params}, 查询: {user_query[:50]}")

        # 路由到对应执行策略
        executor_map = {
            "search": _execute_search,
            "recent": _execute_recent,
            "summary": _execute_summary,
            "platform": _execute_platform,
            "complex": _execute_complex,
            "related": _execute_search,  # related 也走向量搜索
        }

        executor = executor_map.get(intent, _execute_search)

        try:
            result = executor(enhanced_query, params, user_id, llm_func=self._llm)
            # 生成思考过程
            if result.hits:
                result.thinking = self._generate_thinking(user_query, result, conversation_history)
        except Exception as e:
            logger.error(f"[KnowledgeAgent] 查询执行失败: {e}")
            result = QueryResult(
                hits=[],
                overall_summary=f"查询执行失败: {str(e)}",
                total_found=0,
                query_intent=intent,
            )

        # 原则 4：确保每条 MemoryCard 的 5 个必填字段完整
        self._validate_result(result)

        return result

    def _generate_thinking(self, query: str, result: QueryResult, history: Optional[List[dict]] = None) -> str:
        """生成 AI 思考过程"""
        try:
            history_context = ""
            if history and len(history) > 0:
                history_context = f"\n\n参考之前对话:\n" + "\n".join([
                    f"- 用户问: {h.get('content', '')[:100]}"
                    for h in history[-3:]
                ])

            prompt = f"""基于以下信息，用50-100字简洁说明你的检索和推理过程:

用户问题: {query}
找到 {result.total_found} 条相关收藏{history_context}

请直接输出思考过程，不需要输出总结。"""

            thinking = self._llm(prompt, max_tokens=300)
            return thinking.strip() if thinking else ""
        except Exception as e:
            logger.warning(f"[KnowledgeAgent] 生成思考过程失败: {e}")
            return ""

    def _validate_result(self, result: QueryResult) -> None:
        """
        验证 QueryResult 完整性（原则 4）
        修复缺失的必填字段
        """
        required_fields = ["platform_name", "title", "summary", "bookmarked_at", "source_url"]
        for card in result.hits:
            for field in required_fields:
                val = getattr(card, field, None)
                if not val:
                    setattr(card, field, f"[未知{field}]")

        # 确保 total_found 准确
        result.total_found = len(result.hits)

    def format_response(self, result: QueryResult, user_id: str = None, voice: bool = False) -> str:
        """
        将 QueryResult 格式化为用户可见文本
        可选：语音播报
        """
        text = result.format_display()

        if voice and config.TTS_ENABLED:
            try:
                from tts.xtts_output import speak
                speak(result.overall_summary or text[:500])
            except Exception as e:
                logger.debug(f"[KnowledgeAgent] TTS 播报失败: {e}")

        return text
