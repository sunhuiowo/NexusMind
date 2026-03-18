"""
memory/importance_scorer.py
多维度重要性评分系统
LLM 初始评分 + 查询频率 + 时间衰减 + 显式标记 + 关联密度
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import Memory

logger = logging.getLogger(__name__)


# ── 评分权重 ──────────────────────────────────────────────────────────────────
WEIGHT_LLM_INITIAL = 0.40       # LLM 初始评分
WEIGHT_QUERY_FREQUENCY = 0.25   # 查询频率
WEIGHT_RECENCY = 0.20           # 时近性
WEIGHT_RELATION_DENSITY = 0.15  # 关联密度


def llm_initial_score(summary: str, title: str, media_type: str, llm_func=None) -> float:
    """
    LLM 根据内容深度和知识密度打初始分 (0.0 ~ 1.0)
    权重：40%
    """
    if not llm_func:
        return _heuristic_score(summary, title, media_type)

    prompt = f"""请评估以下内容的知识价值和深度，打分 0.0~1.0：
- 0.0~0.3：碎片化信息、随手截图、娱乐内容
- 0.3~0.6：一般参考资料、新闻、普通文章
- 0.6~0.8：有深度的技术/学术内容、实用教程
- 0.8~1.0：深度论文、核心技术文档、重要参考

标题：{title}
类型：{media_type}
摘要：{summary[:300]}

只返回一个0.0到1.0之间的小数，不要其他内容："""

    try:
        result = llm_func(prompt).strip()
        score = float(result)
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.debug(f"[ImportanceScorer] LLM 评分失败，使用启发式: {e}")
        return _heuristic_score(summary, title, media_type)


def _heuristic_score(summary: str, title: str, media_type: str) -> float:
    """启发式初始评分（LLM 不可用时）"""
    score = 0.4  # 基础分

    # 媒体类型加分
    type_bonus = {
        "repo": 0.15,    # 代码仓库通常有价值
        "pdf": 0.10,     # 文档
        "video": 0.05,
        "text": 0.05,
        "audio": 0.05,
        "image": -0.05,  # 图片相对碎片化
    }
    score += type_bonus.get(media_type, 0)

    # 摘要长度（越长说明内容越丰富）
    if len(summary) > 200:
        score += 0.1
    elif len(summary) < 50:
        score -= 0.1

    # 标题关键词
    high_value_keywords = [
        "教程", "深度", "分析", "原理", "架构", "论文", "研究",
        "tutorial", "deep dive", "analysis", "architecture", "research",
        "guide", "complete", "comprehensive", "advanced",
    ]
    title_lower = title.lower()
    for kw in high_value_keywords:
        if kw in title_lower:
            score += 0.1
            break

    return max(0.0, min(1.0, score))


def apply_time_decay(memory: Memory) -> float:
    """
    时间衰减：超过 N 天未访问，每天 × IMPORTANCE_DECAY_RATE
    """
    if not memory.last_accessed_at:
        # 用收藏时间代替
        ref_time_str = memory.bookmarked_at or memory.created_at
    else:
        ref_time_str = memory.last_accessed_at

    try:
        if ref_time_str:
            ref_time = datetime.fromisoformat(ref_time_str.split("T")[0])
        else:
            return memory.importance
    except ValueError:
        return memory.importance

    days_inactive = (datetime.utcnow() - ref_time).days

    if days_inactive <= config.IMPORTANCE_DECAY_DAYS_THRESHOLD:
        return memory.importance

    # 衰减：超过阈值的每天乘以衰减率
    excess_days = days_inactive - config.IMPORTANCE_DECAY_DAYS_THRESHOLD
    decayed = memory.importance * (config.IMPORTANCE_DECAY_RATE ** excess_days)
    return max(0.05, decayed)  # 保底 0.05，防止完全消失


def compute_relation_boost(memory: Memory, store=None) -> float:
    """
    关联密度加分：被多条记忆引用为 related_id 时提升分数
    """
    if not store or not memory.related_ids:
        return 0.0

    # 简单：related_ids 数量越多加分越多（上限 0.1）
    boost = min(0.1, len(memory.related_ids) * 0.02)
    return boost


def recalculate_importance(memory: Memory, store=None, llm_func=None) -> float:
    """
    重新计算综合重要性分数
    结合：LLM 初始分 + 查询频率 + 时间衰减 + 关联密度
    """
    # LLM 初始分（首次计算时评估，后续保存在 importance 中）
    base_score = llm_initial_score(
        memory.summary, memory.title, memory.media_type, llm_func
    )

    # 查询频率加成（上限 0.3）
    frequency_bonus = min(0.3, memory.query_count * config.IMPORTANCE_QUERY_BOOST)

    # 时间衰减
    decayed = apply_time_decay(memory)
    decay_factor = decayed / memory.importance if memory.importance > 0 else 1.0

    # 关联密度加成
    relation_boost = compute_relation_boost(memory, store)

    # 综合分数
    final = (
        base_score * WEIGHT_LLM_INITIAL +
        frequency_bonus * WEIGHT_QUERY_FREQUENCY +
        (1.0 - (1.0 - decay_factor) * 0.5) * WEIGHT_RECENCY +  # 时间因子
        relation_boost * WEIGHT_RELATION_DENSITY
    )

    return max(0.0, min(1.0, final))


def mark_important(memory: Memory) -> Memory:
    """
    用户显式标记「重要」，直接置为 1.0（即时生效）
    """
    memory.importance = 1.0
    memory.last_accessed_at = datetime.utcnow().isoformat()
    return memory


class ImportanceUpdater:
    """
    后台批量更新重要性评分
    由 MemoryAgent 定期调用
    """

    def __init__(self, store, llm_func=None):
        self._store = store
        self._llm_func = llm_func

    def run_batch_update(self, batch_size: int = 100) -> int:
        """
        批量更新长期未访问记忆的重要性
        返回更新条数
        """
        memories = self._store.get_all_for_update(
            last_accessed_before_days=config.IMPORTANCE_DECAY_DAYS_THRESHOLD
        )

        updated = 0
        for memory in memories[:batch_size]:
            new_importance = apply_time_decay(memory)
            if abs(new_importance - memory.importance) > 0.001:
                memory.importance = new_importance
                memory.last_accessed_at = datetime.utcnow().isoformat()
                self._store.update(memory)
                updated += 1

        logger.info(f"[ImportanceUpdater] 批量更新 {updated} 条记忆重要性")
        return updated
