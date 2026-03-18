"""
agents/memory_agent.py
Memory Agent - 后台维护
职责：去重 + 关联维护（related_ids）+ 定期重要性更新
通过 MCP 工具接口操作（原则 3）
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_store import get_memory_store
from memory.importance_scorer import ImportanceUpdater, apply_time_decay
from tools.mcp_tools import find_related, update_importance
from tools.llm import get_llm_client, get_embedder

logger = logging.getLogger(__name__)


class MemoryAgent:
    """
    Memory Agent
    职责：
    1. 后台去重检测（已在 MemoryStore.add 实现，此处做跨平台内容去重）
    2. 关联维护：发现语义相关的记忆，更新 related_ids
    3. 定期重要性衰减更新
    通过 MCP 工具接口与其他 Agent 通信（原则 3）
    """

    def __init__(self):
        self._store = get_memory_store()
        self._llm = get_llm_client()
        self._embedder = get_embedder()
        self._updater = ImportanceUpdater(self._store, llm_func=self._llm)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── 关联维护 ──────────────────────────────────────────────────────────────

    def update_relations_for_memory(
        self,
        memory_id: str,
        top_k: int = 5,
        min_score: float = 0.7,
    ) -> int:
        """
        为指定记忆发现和更新语义关联
        返回发现的关联数
        """
        memory = self._store.get(memory_id)
        if not memory or not memory.summary:
            return 0

        # 通过 MCP find_related 工具（原则 3）
        result = find_related(memory_id=memory_id, top_k=top_k)

        new_related_ids = [
            card.memory_id for card in result.hits
            if card.memory_id and card.memory_id != memory_id
            and card.relevance_score >= min_score
        ]

        if not new_related_ids:
            return 0

        # 合并现有 related_ids（去重）
        existing = set(memory.related_ids)
        combined = list(existing | set(new_related_ids))[:20]  # 最多保留 20 个

        if set(combined) != existing:
            memory.related_ids = combined
            self._store.update(memory)
            logger.debug(f"[MemoryAgent] 更新关联 {memory_id[:8]}: +{len(new_related_ids)} 个")
            return len(new_related_ids)

        return 0

    def batch_update_relations(
        self,
        batch_size: int = 50,
        only_new: bool = True,
    ) -> int:
        """
        批量更新记忆关联
        only_new: 只处理 related_ids 为空的记忆
        """
        conn_db = self._store._db_path
        import sqlite3
        conn = sqlite3.connect(conn_db)

        if only_new:
            rows = conn.execute(
                """SELECT id FROM memories
                   WHERE related_ids = '[]' OR related_ids IS NULL OR related_ids = ''
                   LIMIT ?""",
                (batch_size,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM memories ORDER BY created_at DESC LIMIT ?",
                (batch_size,)
            ).fetchall()

        conn.close()

        total_found = 0
        for row in rows:
            memory_id = row[0]
            try:
                found = self.update_relations_for_memory(memory_id)
                total_found += found
            except Exception as e:
                logger.debug(f"[MemoryAgent] 关联更新失败 {memory_id[:8]}: {e}")

        logger.info(f"[MemoryAgent] 批量关联更新完成，发现 {total_found} 条关联")
        return total_found

    # ── 重要性维护 ────────────────────────────────────────────────────────────

    def run_importance_decay(self, batch_size: int = 200) -> int:
        """执行重要性时间衰减更新"""
        return self._updater.run_batch_update(batch_size=batch_size)

    # ── 去重 ──────────────────────────────────────────────────────────────────

    def detect_cross_platform_duplicates(self, threshold: float = 0.95) -> List[Dict]:
        """
        检测跨平台重复内容（高相似度）
        返回重复组列表
        """
        # 获取最近入库的内容
        import sqlite3
        conn = sqlite3.connect(self._store._db_path)
        rows = conn.execute(
            "SELECT id, title, summary, platform FROM memories ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        conn.close()

        if len(rows) < 2:
            return []

        duplicates = []
        checked = set()

        for i, row_a in enumerate(rows):
            id_a, title_a, summary_a, platform_a = row_a
            if id_a in checked:
                continue

            group = [{"id": id_a, "platform": platform_a, "title": title_a}]

            for row_b in rows[i + 1:]:
                id_b, title_b, summary_b, platform_b = row_b
                if id_b in checked or platform_a == platform_b:
                    continue

                # 标题相似度（简单）
                similarity = _title_similarity(title_a or "", title_b or "")
                if similarity >= threshold:
                    group.append({"id": id_b, "platform": platform_b, "title": title_b})
                    checked.add(id_b)

            if len(group) > 1:
                duplicates.append(group)
                checked.add(id_a)

        return duplicates

    # ── 后台调度 ──────────────────────────────────────────────────────────────

    def start_background(self, interval_hours: float = 24) -> None:
        """启动后台维护任务"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._background_loop,
            args=(interval_hours,),
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[MemoryAgent] 后台任务启动，间隔 {interval_hours}h")

    def stop_background(self) -> None:
        self._running = False

    def _background_loop(self, interval_hours: float) -> None:
        import time
        while self._running:
            try:
                logger.info("[MemoryAgent] 开始后台维护...")
                self.run_importance_decay()
                self.batch_update_relations(batch_size=100)
                logger.info("[MemoryAgent] 后台维护完成")
            except Exception as e:
                logger.error(f"[MemoryAgent] 后台任务异常: {e}")

            time.sleep(interval_hours * 3600)


def _title_similarity(a: str, b: str) -> float:
    """简单标题相似度（Jaccard）"""
    if not a or not b:
        return 0.0
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
