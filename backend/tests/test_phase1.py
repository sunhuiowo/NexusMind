"""
tests/test_phase1.py
Phase 1 集成测试 - 验证核心管道
原则 5：每个 Connector 必须单独集成测试
"""

import sys
import json
import pytest
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from memory.memory_schema import (
    Memory, RawContent, RawBookmark,
    MemoryCard, QueryResult
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 Memory Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestMemorySchema(unittest.TestCase):

    def test_memory_creation(self):
        """Memory 对象创建和序列化"""
        m = Memory(
            platform="youtube",
            platform_name="YouTube",
            platform_id="abc123",
            source_url="https://youtube.com/watch?v=abc123",
            author="Test Channel",
            bookmarked_at="2026-03-14T10:00:00",
            title="LangGraph Tutorial",
            summary="介绍 LangGraph 构建 multi-agent workflow",
            media_type="video",
            tags=["LangGraph", "Agent", "AI"],
            importance=0.7,
        )

        # 必填字段验证
        self.assertEqual(m.platform, "youtube")
        self.assertEqual(m.platform_name, "YouTube")
        self.assertIsNotNone(m.id)
        self.assertIsNotNone(m.created_at)

        # 序列化
        d = m.to_dict()
        self.assertIn("id", d)
        self.assertIn("platform", d)
        self.assertIsInstance(d["tags"], list)

        # 反序列化
        m2 = Memory.from_dict(d)
        self.assertEqual(m.id, m2.id)
        self.assertEqual(m.title, m2.title)

    def test_memory_card_from_memory(self):
        """MemoryCard 从 Memory 生成"""
        m = Memory(
            platform="github",
            platform_name="GitHub Star",
            platform_id="repo123",
            source_url="https://github.com/test/repo",
            author="test-author",
            bookmarked_at="2026-03-14T10:00:00",
            title="test/repo",
            summary="A test repository",
            media_type="repo",
        )

        card = MemoryCard.from_memory(m, relevance_score=0.85)

        # 验证五个必填字段（原则 4）
        self.assertTrue(card.platform_name)
        self.assertTrue(card.title)
        self.assertTrue(card.summary)
        self.assertTrue(card.bookmarked_at)
        self.assertTrue(card.source_url)
        self.assertEqual(card.relevance_score, 0.85)

    def test_query_result_format(self):
        """QueryResult 格式化输出"""
        card = MemoryCard(
            platform_name="YouTube",
            title="LangGraph Tutorial",
            summary="介绍 LangGraph 构建 workflow",
            bookmarked_at="2026-03-14",
            source_url="https://youtube.com/watch?v=abc",
            author="LangChain",
            media_type="video",
            tags=["LangGraph", "AI"],
        )

        result = QueryResult(
            hits=[card],
            overall_summary="这是关于 LangGraph 的教程",
            total_found=1,
            query_intent="search",
        )

        display = result.format_display()
        self.assertIn("LangGraph Tutorial", display)
        self.assertIn("YouTube", display)
        self.assertIn("https://youtube.com", display)

        # JSON 序列化
        d = result.to_dict()
        self.assertEqual(len(d["hits"]), 1)
        self.assertEqual(d["total_found"], 1)
        self.assertIn("platform_name", d["hits"][0])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 Pocket Connector（Mock API）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MOCK_POCKET_API_RESPONSE = {
    "list": {
        "item_001": {
            "item_id": "item_001",
            "given_url": "https://example.com/article",
            "resolved_url": "https://example.com/article",
            "resolved_title": "Understanding LangGraph",
            "given_title": "Understanding LangGraph",
            "excerpt": "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
            "status": "0",
            "time_added": "1710388800",  # 2024-03-14
            "tags": {"langgraph": {}, "ai": {}},
            "authors": {"1": {"name": "John Doe", "item_id": "item_001", "author_id": "1"}},
            "images": {},
            "has_video": "0",
            "word_count": "500",
        }
    }
}


class TestPocketConnector(unittest.TestCase):

    def setUp(self):
        """测试前设置 Mock"""
        # 设置测试用 token
        from auth.token_store import get_token_store, TokenData
        store = get_token_store()
        store.save(TokenData(
            platform="pocket",
            auth_mode="oauth2",
            access_token="mock_access_token",
            status="connected",
            extra={"username": "test_user"},
        ))

    @patch("platforms.pocket_connector.config")
    @patch("requests.post")
    def test_fetch_bookmarks_normalize(self, mock_post, mock_config):
        """验证 Pocket normalize() 输出完整符合 RawContent 规范（原则 5）"""
        mock_config.POCKET_CONSUMER_KEY = "mock_consumer_key"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_POCKET_API_RESPONSE
        mock_post.return_value = mock_response

        from platforms.pocket_connector import PocketConnector
        connector = PocketConnector()
        connector._access_token = "mock_access_token"

        bookmarks = connector.fetch_bookmarks(limit=10)
        self.assertEqual(len(bookmarks), 1)

        bm = bookmarks[0]
        self.assertEqual(bm.platform, "pocket")
        self.assertEqual(bm.platform_id, "item_001")
        self.assertTrue(bm.url)
        self.assertTrue(bm.title)

        content = connector.fetch_content(bm)

        # 验证必填字段（原则 5）
        self.assertEqual(content.platform, "pocket")
        self.assertEqual(content.platform_name, "Pocket")
        self.assertTrue(content.platform_id)
        self.assertTrue(content.url)
        self.assertTrue(content.title)
        self.assertEqual(content.media_type, "text")

        # 验证 validate_raw_content
        self.assertTrue(connector.validate_raw_content(content))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 MemoryStore
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestMemoryStore(unittest.TestCase):

    def setUp(self):
        """使用临时文件作为测试 DB"""
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.tmp_dir}/test.db"
        self.faiss_path = f"{self.tmp_dir}/faiss"

    def test_add_and_get(self):
        """添加和查询记忆"""
        from memory.memory_store import MemoryStore
        store = MemoryStore(
            faiss_path=self.faiss_path,
            db_path=self.db_path,
            embedding_dim=8,  # 小维度用于测试
        )

        m = Memory(
            platform="pocket",
            platform_name="Pocket",
            platform_id="test_001",
            source_url="https://example.com",
            title="Test Article",
            summary="A test article about AI",
            media_type="text",
            embedding=[0.1] * 8,
            bookmarked_at="2026-03-14T10:00:00",
        )

        # 添加
        success = store.add(m)
        self.assertTrue(success)

        # 查询
        retrieved = store.get(m.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, "Test Article")

        # 去重：再次添加同一内容应跳过
        success2 = store.add(m)
        self.assertFalse(success2)

    def test_exists_by_platform_id(self):
        """去重检查"""
        from memory.memory_store import MemoryStore
        store = MemoryStore(
            faiss_path=self.faiss_path,
            db_path=self.db_path,
            embedding_dim=8,
        )

        m = Memory(
            platform="github",
            platform_name="GitHub Star",
            platform_id="repo_999",
            source_url="https://github.com/test",
            title="Test Repo",
            summary="A test repo",
            media_type="repo",
            bookmarked_at="2026-03-14T10:00:00",
        )
        store.add(m)

        self.assertTrue(store.exists_by_platform_id("github", "repo_999"))
        self.assertFalse(store.exists_by_platform_id("github", "repo_000"))

    def test_stats(self):
        """统计信息"""
        from memory.memory_store import MemoryStore
        store = MemoryStore(
            faiss_path=self.faiss_path,
            db_path=self.db_path,
            embedding_dim=8,
        )

        for i in range(3):
            store.add(Memory(
                platform="pocket",
                platform_name="Pocket",
                platform_id=f"stat_{i}",
                source_url=f"https://example.com/{i}",
                title=f"Article {i}",
                summary="Summary",
                media_type="text",
                bookmarked_at="2026-03-14T10:00:00",
            ))

        stats = store.get_stats()
        self.assertEqual(stats["total"], 3)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 Knowledge Agent 意图识别
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestKnowledgeAgentIntent(unittest.TestCase):

    def test_intent_detection(self):
        """意图识别覆盖测试"""
        from agents.knowledge_agent import _detect_intent

        cases = [
            ("我最近7天收藏了什么", "recent"),
            ("最近3天有什么新收藏", "recent"),
            ("总结我关于 Agent 的所有收藏", "summary"),
            ("GitHub 上 Star 了哪些 Python 项目", "platform"),
            ("YouTube 和 B站的 AI 视频按主题分类", "complex"),
            ("我收藏过 LangGraph 相关内容吗", "search"),
        ]

        for query, expected_intent in cases:
            intent, _ = _detect_intent(query)
            self.assertEqual(intent, expected_intent,
                             f"查询 '{query}' 应识别为 '{expected_intent}'，实际为 '{intent}'")

    def test_platform_detection(self):
        """平台关键词识别"""
        from agents.knowledge_agent import _detect_intent

        intent, params = _detect_intent("GitHub 上 Star 了哪些 Python 项目")
        self.assertEqual(params.get("platform"), "github")

        intent, params = _detect_intent("我在 Bilibili 收藏了哪些视频")
        self.assertEqual(params.get("platform"), "bilibili")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 Auth 加密
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTokenStore(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())

    @patch("auth.token_store.config")
    def test_encrypt_decrypt(self, mock_config):
        """AES-256-GCM 加解密验证"""
        mock_config.AUTH_DIR = str(self.tmp_dir)
        mock_config.TOKEN_ENCRYPT_KEY = ""
        mock_config.TOKEN_MASTER_PASSWORD = ""
        mock_config.COOKIE_EXPIRE_WARN_DAYS = 7
        mock_config.TOKEN_REFRESH_BEFORE_MINUTES = 5

        from auth.token_store import TokenStore, TokenData
        store = TokenStore(master_password="test-password-123")

        token = TokenData(
            platform="test_platform",
            auth_mode="oauth2",
            access_token="secret_access_token_xyz",
            refresh_token="secret_refresh_token_abc",
            status="connected",
        )

        store.save(token)
        loaded = store.load("test_platform")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.access_token, "secret_access_token_xyz")
        self.assertEqual(loaded.refresh_token, "secret_refresh_token_abc")
        self.assertEqual(loaded.status, "connected")

    @patch("auth.token_store.config")
    def test_mark_needs_reauth(self, mock_config):
        """needs_reauth 状态标记"""
        mock_config.AUTH_DIR = str(self.tmp_dir)
        mock_config.TOKEN_ENCRYPT_KEY = ""
        mock_config.TOKEN_MASTER_PASSWORD = ""
        mock_config.COOKIE_EXPIRE_WARN_DAYS = 7
        mock_config.TOKEN_REFRESH_BEFORE_MINUTES = 5

        from auth.token_store import TokenStore, TokenData
        store = TokenStore(master_password="test-password-123")

        store.save(TokenData(
            platform="xiaohongshu",
            auth_mode="cookie",
            cookie="test_cookie",
            status="connected",
        ))

        store.mark_needs_reauth("xiaohongshu", "Cookie 已失效")
        loaded = store.load("xiaohongshu")
        self.assertEqual(loaded.status, "needs_reauth")


if __name__ == "__main__":
    unittest.main(verbosity=2)
