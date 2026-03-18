#!/usr/bin/env python3
"""测试 B站连接器"""
import sys
sys.path.insert(0, ".")

from platforms.bilibili_connector import BilibiliConnector

connector = BilibiliConnector()

# 测试认证
print("=== 测试认证 ===")
if connector.is_authenticated():
    print("✓ 已认证")
    print(f"  auth_mode: {connector.get_auth_mode()}")
else:
    print("✗ 未认证")
    sys.exit(1)

# 测试获取书签
print("\n=== 测试获取收藏 ===")
bookmarks = connector.fetch_bookmarks(limit=5)
print(f"获取到 {len(bookmarks)} 条收藏")

for i, bm in enumerate(bookmarks[:3]):
    print(f"\n--- 书签 {i+1} ---")
    print(f"  title: {bm.title}")
    print(f"  url: {bm.url}")
    print(f"  bookmarked_at: {bm.bookmarked_at}")

# 测试获取内容
print("\n=== 测试获取内容详情 ===")
if bookmarks:
    content = connector.fetch_content(bookmarks[0])
    print(f"  title: {content.title}")
    print(f"  body: {content.body[:200] if content.body else '(empty)'}...")
    print(f"  author: {content.author}")
