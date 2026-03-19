"""
tests/test_user_store.py
UserStore 单元测试
"""

import sys
import pytest
import uuid
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from auth.user_store import UserStore, get_user_store


class TestUserStore(unittest.TestCase):
    """UserStore 测试套件"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前创建临时数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_users.db")
        self.store = UserStore(db_path=self.db_path)
        yield
        # 清理
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_user_store_creates_tables(self):
        """验证 UserStore 初始化时创建必要的表"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 检查 users 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        self.assertIsNotNone(cursor.fetchone(), "users 表应该被创建")

        # 检查 sessions 表存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        self.assertIsNotNone(cursor.fetchone(), "sessions 表应该被创建")

        # 检查 users 表结构
        cursor.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cursor.fetchall()}
        required_cols = {'id', 'username', 'password_hash', 'is_admin', 'created_at'}
        self.assertTrue(required_cols.issubset(columns), f"users 表缺少列: {required_cols - columns}")

        # 检查 sessions 表结构
        cursor.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in cursor.fetchall()}
        required_cols = {'id', 'user_id', 'created_at', 'expires_at'}
        self.assertTrue(required_cols.issubset(columns), f"sessions 表缺少列: {required_cols - columns}")

        conn.close()

    def test_register_creates_user(self):
        """注册新用户应该成功创建用户记录"""
        user_id, error = self.store.register_user("testuser", "password123")

        self.assertIsNone(error, f"注册不应出错: {error}")
        self.assertIsNotNone(user_id, "应返回用户ID")
        self.assertTrue(user_id.startswith("user_"), f"用户ID应以 user_ 开头: {user_id}")

        # 验证用户可以登录
        result = self.store.login_user("testuser", "password123")
        self.assertIsNotNone(result, "新注册用户应该可以登录")
        self.assertEqual(result["username"], "testuser")

    def test_register_duplicate_username(self):
        """重复注册相同用户名应该返回错误"""
        # 第一次注册应该成功
        user_id1, error1 = self.store.register_user("duplicateuser", "password123")
        self.assertIsNone(error1, f"第一次注册不应出错: {error1}")

        # 第二次注册相同用户名应该失败
        user_id2, error2 = self.store.register_user("duplicateuser", "password456")
        self.assertIsNotNone(error2, "重复用户名应该返回错误")
        self.assertIsNone(user_id2, "重复注册不应返回用户ID")

    def test_login_success(self):
        """正确用户名和密码应该登录成功"""
        # 先注册
        self.store.register_user("loginuser", "correctpassword")

        # 登录
        result = self.store.login_user("loginuser", "correctpassword")

        self.assertIsNotNone(result, "正确凭据应该登录成功")
        self.assertEqual(result["username"], "loginuser")
        self.assertIn("session_id", result)
        self.assertIn("user_id", result)
        self.assertFalse(result.get("is_admin", False), "普通用户不应是 admin")

    def test_login_wrong_password(self):
        """错误密码应该登录失败"""
        # 先注册
        self.store.register_user("wrongpwuser", "correctpassword")

        # 使用错误密码登录
        result = self.store.login_user("wrongpwuser", "wrongpassword")

        self.assertIsNone(result, "错误密码应该登录失败")

    def test_session_validation(self):
        """有效 session_id 应该通过验证并返回 user_id"""
        # 注册并登录
        self.store.register_user("sessionuser", "password")
        login_result = self.store.login_user("sessionuser", "password")

        session_id = login_result["session_id"]
        user_id = login_result["user_id"]

        # 验证 session
        validated_user_id = self.store.validate_session(session_id)

        self.assertEqual(validated_user_id, user_id, "有效 session 应返回正确的 user_id")

    def test_session_invalid(self):
        """无效 session_id 应该返回 None"""
        # 使用随机 session_id 验证
        fake_session_id = str(uuid.uuid4())

        result = self.store.validate_session(fake_session_id)

        self.assertIsNone(result, "无效 session_id 应该返回 None")

    def test_logout(self):
        """登出应该使 session 失效"""
        # 注册并登录
        self.store.register_user("logoutuser", "password")
        login_result = self.store.login_user("logoutuser", "password")

        session_id = login_result["session_id"]

        # 登出
        self.store.logout_user(session_id)

        # session 应该失效
        result = self.store.validate_session(session_id)
        self.assertIsNone(result, "登出后 session 应该失效")

    def test_get_user(self):
        """获取用户信息应该返回正确数据"""
        # 注册
        user_id, _ = self.store.register_user("getuser", "password")

        # 获取用户
        user = self.store.get_user(user_id)

        self.assertIsNotNone(user, "应该返回用户信息")
        self.assertEqual(user["id"], user_id)
        self.assertEqual(user["username"], "getuser")
        self.assertFalse(user.get("is_admin", False))

    def test_list_users(self):
        """列出所有用户应该返回所有注册用户"""
        # 注册多个用户
        self.store.register_user("user1", "password1")
        self.store.register_user("user2", "password2")
        self.store.register_user("user3", "password3")

        # 列出用户
        users = self.store.list_users()

        self.assertEqual(len(users), 3, "应该返回3个用户")
        usernames = {u["username"] for u in users}
        self.assertEqual(usernames, {"user1", "user2", "user3"})

    def test_delete_user(self):
        """删除用户应该移除用户及其会话"""
        # 注册用户
        user_id, _ = self.store.register_user("deleteuser", "password")

        # 登录创建 session
        login_result = self.store.login_user("deleteuser", "password")
        session_id = login_result["session_id"]

        # 删除用户
        result = self.store.delete_user(user_id)
        self.assertTrue(result, "删除用户应该返回成功")

        # 用户应该不存在
        user = self.store.get_user(user_id)
        self.assertIsNone(user, "删除的用户不应该存在")

        # session 应该失效
        validated = self.store.validate_session(session_id)
        self.assertIsNone(validated, "删除用户的 session 应该失效")

        # 用户列表中不应包含
        users = self.store.list_users()
        usernames = {u["username"] for u in users}
        self.assertNotIn("deleteuser", usernames)