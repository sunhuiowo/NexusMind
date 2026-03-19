"""
memory/memory_store.py
FAISS + SQLite 双写封装
向量索引 + 结构化元数据存储
"""

import json
import logging
import sqlite3
import threading
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

# Context variable to store current user_id for request-scoped storage
_current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)


def set_current_user(user_id: Optional[str]) -> None:
    """设置当前请求的用户ID"""
    _current_user_id.set(user_id)


def get_current_user() -> Optional[str]:
    """获取当前请求的用户ID"""
    return _current_user_id.get()

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import Memory
from memory.hybrid_search import HybridSearcher, KeywordExtractor

logger = logging.getLogger(__name__)

# 线程本地 SQLite 连接
_local = threading.local()


def _get_db_conn(db_path: str) -> sqlite3.Connection:
    """获取线程本地 SQLite 连接（每个 db_path 独立连接）"""
    # Store (conn, db_path) tuple to ensure we use correct connection for each db
    if not hasattr(_local, "conn_info") or _local.conn_info is None or _local.conn_info[1] != db_path:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn_info = (conn, db_path)
    return _local.conn_info[0]


class MemoryStore:
    """
    FAISS 向量索引 + SQLite 元数据库双写封装
    原则：Embedding 只基于 summary 字段生成
    """

    def __init__(
        self,
        faiss_path: str = None,
        db_path: str = None,
        embedding_dim: int = None,
    ):
        self._faiss_path = faiss_path or config.FAISS_INDEX_PATH
        self._db_path = db_path or config.METADATA_DB_PATH
        self._dim = embedding_dim or config.EMBEDDING_DIM
        self._lock = threading.Lock()

        # FAISS 索引（ID 映射模式）
        self._index = None
        self._id_to_pos: Dict[str, int] = {}   # memory_id -> faiss index position
        self._pos_to_id: Dict[int, str] = {}   # faiss position -> memory_id

        self._init_db()
        self._load_or_create_index()

    # ── SQLite ────────────────────────────────────────────────────────────────

    def _init_db(self):
        """初始化 SQLite 表结构"""
        conn = _get_db_conn(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                user_id TEXT NOT NULL,
                id TEXT PRIMARY KEY,
                created_at TEXT,
                platform TEXT,
                platform_name TEXT,
                platform_id TEXT,
                source_url TEXT,
                author TEXT,
                bookmarked_at TEXT,
                title TEXT,
                summary TEXT,
                raw_content TEXT,
                tags TEXT,          -- JSON array
                media_type TEXT,
                thumbnail_url TEXT,
                importance REAL DEFAULT 0.5,
                query_count INTEGER DEFAULT 0,
                last_accessed_at TEXT,
                related_ids TEXT,   -- JSON array
                parent_id TEXT,
                faiss_pos INTEGER   -- position in FAISS index
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform ON memories(platform)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bookmarked_at ON memories(bookmarked_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_id ON memories(platform, platform_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC)
        """)
        conn.commit()
        logger.info(f"[MemoryStore] SQLite 初始化完成: {self._db_path}")

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["related_ids"] = json.loads(d.get("related_ids") or "[]")
        d["embedding"] = []  # 不从 DB 加载 embedding（从 FAISS 取）
        return Memory.from_dict(d)

    def _memory_to_params(self, memory: Memory, faiss_pos: int = -1) -> tuple:
        return (
            memory.user_id,
            memory.id,
            memory.created_at,
            memory.platform,
            memory.platform_name,
            memory.platform_id,
            memory.source_url,
            memory.author,
            memory.bookmarked_at,
            memory.title,
            memory.summary,
            memory.raw_content[:10000] if memory.raw_content else "",  # 限制存储大小
            json.dumps(memory.tags, ensure_ascii=False),
            memory.media_type,
            memory.thumbnail_url,
            memory.importance,
            memory.query_count,
            memory.last_accessed_at,
            json.dumps(memory.related_ids, ensure_ascii=False),
            memory.parent_id,
            faiss_pos,
        )

    # ── FAISS ─────────────────────────────────────────────────────────────────

    def _load_or_create_index(self):
        """加载或创建 FAISS 索引"""
        try:
            import faiss
        except ImportError:
            logger.warning("[MemoryStore] faiss-cpu 未安装，向量检索将不可用")
            return

        faiss_file = self._faiss_path + ".index"
        map_file = self._faiss_path + ".map.json"

        if Path(faiss_file).exists() and Path(map_file).exists():
            try:
                self._index = faiss.read_index(faiss_file)
                with open(map_file, "r") as f:
                    map_data = json.load(f)
                self._id_to_pos = map_data.get("id_to_pos", {})
                self._pos_to_id = {int(k): v for k, v in map_data.get("pos_to_id", {}).items()}
                logger.info(f"[MemoryStore] FAISS 索引加载成功，共 {self._index.ntotal} 条")
                return
            except Exception as e:
                logger.warning(f"[MemoryStore] FAISS 索引加载失败，重建: {e}")

        # 创建新索引（内积，配合归一化向量实现余弦相似度）
        self._index = faiss.IndexFlatIP(self._dim)
        logger.info(f"[MemoryStore] FAISS 新索引创建，dim={self._dim}")

    def _save_index(self):
        """持久化 FAISS 索引"""
        try:
            import faiss
            faiss_file = self._faiss_path + ".index"
            map_file = self._faiss_path + ".map.json"

            Path(self._faiss_path).parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, faiss_file)

            with open(map_file, "w") as f:
                json.dump({
                    "id_to_pos": self._id_to_pos,
                    "pos_to_id": self._pos_to_id,
                }, f)
        except Exception as e:
            logger.error(f"[MemoryStore] FAISS 持久化失败: {e}")

    # ── 核心 CRUD ─────────────────────────────────────────────────────────────

    def add(self, memory: Memory, defer_commit: bool = False) -> bool:
        """
        添加记忆（FAISS + SQLite 双写）
        原则：Embedding 必须基于 summary 字段，严禁使用 raw_content

        Args:
            memory: 记忆对象
            defer_commit: 是否延迟 commit（用于批量操作，减少 IO）
        """
        with self._lock:
            # 确保 user_id 已设置
            if not memory.user_id:
                memory.user_id = get_current_user() or "_default"
                if memory.user_id == "_default":
                    logger.warning(f"[MemoryStore] Memory saved with user_id='_default' (no user context)")

            if not memory.id:
                import uuid
                memory.id = str(uuid.uuid4())

            # 去重检查
            if self.exists_by_platform_id(memory.platform, memory.platform_id, memory.user_id):
                logger.debug(f"[MemoryStore] 已存在，跳过: {memory.platform}/{memory.platform_id}")
                return False

            faiss_pos = -1

            # 写入 FAISS（如果有 embedding）
            if memory.embedding and self._index is not None:
                vec = np.array([memory.embedding], dtype=np.float32)
                # 归一化（余弦相似度）
                norm = np.linalg.norm(vec, axis=1, keepdims=True)
                if norm[0][0] > 0:
                    vec = vec / norm

                faiss_pos = self._index.ntotal
                self._index.add(vec)
                self._id_to_pos[memory.id] = faiss_pos
                self._pos_to_id[faiss_pos] = memory.id

            # 写入 SQLite
            conn = _get_db_conn(self._db_path)
            conn.execute("""
                INSERT INTO memories (user_id, id, created_at, platform, platform_name, platform_id, source_url, author, bookmarked_at, title, summary, raw_content, tags, media_type, thumbnail_url, importance, query_count, last_accessed_at, related_ids, parent_id, faiss_pos) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
            """, self._memory_to_params(memory, faiss_pos))

            if not defer_commit:
                conn.commit()
                # 只在非延迟模式下保存索引
                if faiss_pos >= 0:
                    self._save_index()

            logger.debug(f"[MemoryStore] 入库成功: {memory.title[:30]}")
            return True

    def add_batch(self, memories: List[Memory]) -> List[bool]:
        """
        批量添加记忆（优化版）

        Args:
            memories: 记忆列表

        Returns:
            成功列表 [True, False, ...]
        """
        if not memories:
            return []

        with self._lock:
            results = []
            conn = _get_db_conn(self._db_path)

            for memory in memories:
                # 确保 user_id 已设置
                if not memory.user_id:
                    memory.user_id = get_current_user() or "_default"
                    if memory.user_id == "_default":
                        logger.warning(f"[MemoryStore] Memory {memory.id} saved with user_id='_default' (no user context)")

                if not memory.id:
                    import uuid
                    memory.id = str(uuid.uuid4())

                # 去重检查
                if self.exists_by_platform_id(memory.platform, memory.platform_id, memory.user_id):
                    results.append(False)
                    continue

                faiss_pos = -1

                # 写入 FAISS
                if memory.embedding and self._index is not None:
                    vec = np.array([memory.embedding], dtype=np.float32)
                    norm = np.linalg.norm(vec, axis=1, keepdims=True)
                    if norm[0][0] > 0:
                        vec = vec / norm

                    faiss_pos = self._index.ntotal
                    self._index.add(vec)
                    self._id_to_pos[memory.id] = faiss_pos
                    self._pos_to_id[faiss_pos] = memory.id

                # 写入 SQLite
                conn.execute("""
                    INSERT INTO memories (user_id, id, created_at, platform, platform_name, platform_id, source_url, author, bookmarked_at, title, summary, raw_content, tags, media_type, thumbnail_url, importance, query_count, last_accessed_at, related_ids, parent_id, faiss_pos) VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
                """, self._memory_to_params(memory, faiss_pos))
                results.append(True)

            # 批量提交
            conn.commit()
            # 批量保存索引
            self._save_index()

            logger.info(f"[MemoryStore] 批量入库完成: {sum(results)}/{len(memories)} 条")
            return results

    def update(self, memory: Memory) -> bool:
        """更新记忆元数据（不更新 embedding）"""
        with self._lock:
            if not memory.user_id:
                memory.user_id = get_current_user() or "_default"
            conn = _get_db_conn(self._db_path)
            conn.execute("""
                UPDATE memories SET
                    summary=?, tags=?, importance=?, query_count=?,
                    last_accessed_at=?, related_ids=?, raw_content=?
                WHERE id=? AND user_id=?
            """, (
                memory.summary,
                json.dumps(memory.tags, ensure_ascii=False),
                memory.importance,
                memory.query_count,
                memory.last_accessed_at,
                json.dumps(memory.related_ids, ensure_ascii=False),
                memory.raw_content[:10000] if memory.raw_content else "",
                memory.id,
                memory.user_id,
            ))
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0] > 0

    def delete(self, memory_id: str, user_id: str = "") -> bool:
        """删除记忆（SQLite 删除，FAISS 标记废弃）"""
        if not user_id:
            user_id = get_current_user()
        with self._lock:
            conn = _get_db_conn(self._db_path)
            conn.execute("DELETE FROM memories WHERE id=? AND user_id=?", (memory_id, user_id))
            conn.commit()
            # FAISS 不支持直接删除，下次重建时清理
            if memory_id in self._id_to_pos:
                pos = self._id_to_pos.pop(memory_id)
                self._pos_to_id.pop(pos, None)
            return True

    def delete_all(self) -> bool:
        """删除所有记忆数据（SQLite + FAISS 清空）"""
        with self._lock:
            try:
                # 清空 SQLite 表
                conn = _get_db_conn(self._db_path)
                # WARNING: This deletes ALL memories for ALL users. Use with extreme caution.
                conn.execute("DELETE FROM memories")
                conn.commit()
                logger.info(f"[MemoryStore] SQLite 数据已清空")

                # 清空 FAISS 索引
                if self._index is not None:
                    try:
                        import faiss
                        # 重新创建空索引
                        self._index = faiss.IndexFlatIP(self._dim)
                        self._id_to_pos.clear()
                        self._pos_to_id.clear()
                        self._save_index()
                        logger.info(f"[MemoryStore] FAISS 索引已清空")
                    except ImportError:
                        logger.warning("[MemoryStore] faiss-cpu 未安装，跳过 FAISS 清空")

                return True
            except Exception as e:
                logger.error(f"[MemoryStore] 清空数据失败: {e}")
                return False

    def get(self, memory_id: str, user_id: str = "") -> Optional[Memory]:
        """按 ID 查询记忆"""
        if not user_id:
            user_id = get_current_user()
        conn = _get_db_conn(self._db_path)
        row = conn.execute("SELECT * FROM memories WHERE id=? AND user_id=?", (memory_id, user_id)).fetchone()
        return self._row_to_memory(row) if row else None

    def exists_by_platform_id(self, platform: str, platform_id: str, user_id: str = "") -> bool:
        """按平台 + 平台侧 ID 去重查询"""
        conn = _get_db_conn(self._db_path)
        # Lazy init: if this is a new thread connection, table might not exist yet
        if not user_id:
            user_id = get_current_user()
        try:
            row = conn.execute(
                "SELECT id FROM memories WHERE platform=? AND platform_id=? AND user_id=?",
                (platform, platform_id, user_id),
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                self._init_db()
                row = conn.execute(
                    "SELECT id FROM memories WHERE platform=? AND platform_id=? AND user_id=?",
                    (platform, platform_id, user_id),
                ).fetchone()
                return row is not None
            raise

    # ── 检索 ──────────────────────────────────────────────────────────────────

    def search_by_vector(
        self,
        query_embedding: List[float],
        query_text: str = None,  # 原始查询文本，用于关键词匹配
        top_k: int = None,
        platform_filter: str = None,
        media_type_filter: str = None,
        min_importance: float = 0.0,
        use_hybrid: bool = True,  # 是否使用混合检索
    ) -> List[Tuple[Memory, float]]:
        """
        向量语义检索（支持混合检索）
        返回 [(Memory, relevance_score), ...] 按相关度排序
        """
        top_k = top_k or config.TOP_K_RESULTS
        user_id = get_current_user()

        if self._index is None or self._index.ntotal == 0:
            logger.warning("[MemoryStore] FAISS 索引为空")
            return []

        vec = np.array([query_embedding], dtype=np.float32)
        norm = np.linalg.norm(vec, axis=1, keepdims=True)
        if norm[0][0] > 0:
            vec = vec / norm

        # 多取一些，用于过滤后仍有足够结果
        k = min(top_k * 8, self._index.ntotal)  # 增加候选数量以支持重排序
        scores, indices = self._index.search(vec, k)

        # 收集向量检索结果
        vector_results = []
        vector_scores = {}
        conn = _get_db_conn(self._db_path)

        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            memory_id = self._pos_to_id.get(int(idx))
            if not memory_id:
                continue

            row = conn.execute("SELECT * FROM memories WHERE id=? AND user_id=?", (memory_id, user_id)).fetchone()
            if not row:
                continue

            memory = self._row_to_memory(row)

            # 过滤条件
            if platform_filter and memory.platform != platform_filter:
                continue
            if media_type_filter and memory.media_type != media_type_filter:
                continue
            if memory.importance < min_importance:
                continue

            # 基础向量分数
            base_score = float(score) * 0.7 + memory.importance * 0.3
            vector_results.append(memory)
            vector_scores[memory_id] = base_score

        # 如果启用混合检索且有查询文本，进行关键词重排序
        if use_hybrid and query_text and vector_results:
            logger.info(f"[MemoryStore] 使用混合检索，查询: '{query_text[:50]}...'")
            try:
                hybrid_searcher = HybridSearcher()
                results = hybrid_searcher.search(
                    query=query_text,
                    query_embedding=query_embedding,
                    memories=vector_results,
                    vector_scores=vector_scores,
                    top_k=top_k,
                    vector_weight=0.6,
                    keyword_weight=0.4,
                )
                return results
            except Exception as e:
                logger.warning(f"[MemoryStore] 混合检索失败，回退到纯向量检索: {e}")

        # 纯向量检索结果
        results = [(m, vector_scores[m.id]) for m in vector_results[:top_k]]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def search_by_time(
        self,
        days: int = 7,
        platform: str = None,
        media_type: str = None,
        limit: int = None,
    ) -> List[Memory]:
        """按时间倒序查询"""
        limit = limit or config.TOP_K_RESULTS
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        user_id = get_current_user()

        conn = _get_db_conn(self._db_path)
        query = "SELECT * FROM memories WHERE bookmarked_at >= ? AND user_id=?"
        params: list = [cutoff, user_id]

        if platform:
            query += " AND platform=?"
            params.append(platform)
        if media_type:
            query += " AND media_type=?"
            params.append(media_type)

        query += " ORDER BY bookmarked_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def search_by_platform(
        self,
        platform: str,
        topic_query_ids: List[str] = None,
        limit: int = None,
    ) -> List[Memory]:
        """按平台过滤查询"""
        limit = limit or config.TOP_K_RESULTS
        user_id = get_current_user()
        conn = _get_db_conn(self._db_path)

        if topic_query_ids:
            placeholders = ",".join("?" * len(topic_query_ids))
            rows = conn.execute(
                f"SELECT * FROM memories WHERE platform=? AND id IN ({placeholders}) AND user_id=? ORDER BY importance DESC LIMIT ?",
                [platform] + topic_query_ids + [user_id, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE platform=? AND user_id=? ORDER BY importance DESC, bookmarked_at DESC LIMIT ?",
                (platform, user_id, limit),
            ).fetchall()

        return [self._row_to_memory(r) for r in rows]

    def search_by_tags(
        self,
        tags: List[str],
        match_mode: str = "any",  # any / all
        limit: int = None,
    ) -> List[Memory]:
        """按标签查询"""
        limit = limit or config.TOP_K_RESULTS
        user_id = get_current_user()
        conn = _get_db_conn(self._db_path)

        # SQLite JSON 查询标签（使用 LIKE 模糊匹配）
        results = []
        all_rows = conn.execute(
            "SELECT * FROM memories WHERE user_id=? ORDER BY importance DESC",
            (user_id,)
        ).fetchall()

        for row in all_rows:
            memory = self._row_to_memory(row)
            memory_tags = [t.lower() for t in memory.tags]

            if match_mode == "all":
                if all(t.lower() in memory_tags for t in tags):
                    results.append(memory)
            else:  # any
                if any(t.lower() in memory_tags for t in tags):
                    results.append(memory)

            if len(results) >= limit:
                break

        return results

    def get_all_for_update(
        self,
        last_accessed_before_days: int = 30,
    ) -> List[Memory]:
        """获取需要重要性更新的记忆"""
        cutoff = (datetime.utcnow() - timedelta(days=last_accessed_before_days)).isoformat()
        user_id = get_current_user()
        conn = _get_db_conn(self._db_path)
        rows = conn.execute(
            """SELECT * FROM memories
               WHERE (last_accessed_at < ? OR last_accessed_at IS NULL OR last_accessed_at = '') AND user_id=?
               ORDER BY importance DESC""",
            (cutoff, user_id),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def increment_query_count(self, memory_id: str, user_id: str = "") -> None:
        """命中后增加查询计数并更新 importance"""
        if not user_id:
            user_id = get_current_user()
        conn = _get_db_conn(self._db_path)
        conn.execute("""
            UPDATE memories SET
                query_count = query_count + 1,
                importance = MIN(1.0, importance + ?),
                last_accessed_at = ?
            WHERE id=? AND user_id=?
        """, (config.IMPORTANCE_QUERY_BOOST, datetime.utcnow().isoformat(), memory_id, user_id))
        conn.commit()

    def get_stats(self, platform_filter: str = None) -> Dict[str, Any]:
        """统计信息"""
        user_id = get_current_user()
        conn = _get_db_conn(self._db_path)

        if platform_filter:
            total = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE platform=? AND user_id=?", (platform_filter, user_id)
            ).fetchone()[0]
            return {"total": total, "platform": platform_filter}

        total = conn.execute("SELECT COUNT(*) FROM memories WHERE user_id=?", (user_id,)).fetchone()[0]
        by_platform = conn.execute(
            "SELECT platform_name, COUNT(*) as cnt FROM memories WHERE user_id=? GROUP BY platform ORDER BY cnt DESC",
            (user_id,)
        ).fetchall()
        by_type = conn.execute(
            "SELECT media_type, COUNT(*) as cnt FROM memories WHERE user_id=? GROUP BY media_type ORDER BY cnt DESC",
            (user_id,)
        ).fetchall()

        return {
            "total": total,
            "by_platform": [{"platform": r[0], "count": r[1]} for r in by_platform],
            "by_media_type": [{"type": r[0], "count": r[1]} for r in by_type],
        }


# ── 用户隔离的存储实例 ─────────────────────────────────────────────────────────
# 每个用户有独立的 MemoryStore 实例，使用用户ID区分存储路径
_stores: Dict[str, MemoryStore] = {}


def get_memory_store(user_id: str) -> MemoryStore:
    """
    Get a MemoryStore for the specified user.
    user_id is REQUIRED - no default, no ContextVar fallback.
    Raises ValueError if user_id is empty.
    """
    global _stores

    if not user_id:
        raise ValueError("get_memory_store() requires explicit user_id. "
                        "Use request.state.user_id from SessionMiddleware.")

    # If this user's store instance doesn't exist, create it
    if user_id not in _stores:
        # _default 用户使用原始数据库（向后兼容），其他用户使用独立的存储路径
        if user_id == "_default":
            # 使用原始的 memories.db 和 faiss_index（向后兼容）
            user_db_path = config.METADATA_DB_PATH
            user_faiss_path = str(config.VECTOR_DIR / "faiss_index")
        else:
            user_db_path = str(config.DATA_DIR / f"memories_{user_id}.db")
            user_faiss_path = str(config.VECTOR_DIR / user_id / "index.faiss")

        # 确保目录存在（FAISS目录和数据库目录）
        Path(user_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(user_faiss_path).parent.mkdir(parents=True, exist_ok=True)

        _stores[user_id] = MemoryStore(
            faiss_path=user_faiss_path,
            db_path=user_db_path,
        )
        logger.info(f"Created new MemoryStore for user: {user_id}, db_path: {user_db_path}")

    return _stores[user_id]


def clear_user_store(user_id: str) -> None:
    """清除指定用户的存储实例和数据"""
    global _stores
    if user_id in _stores:
        del _stores[user_id]
        logger.info(f"Cleared MemoryStore for user: {user_id}")
