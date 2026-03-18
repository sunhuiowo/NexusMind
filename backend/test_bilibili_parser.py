#!/usr/bin/env python3
"""测试 B站视频解析器"""
import sys
sys.path.insert(0, ".")

from parsers.bilibili_parser import parse_bilibili_video, BilibiliParser

# 测试BV号提取
test_urls = [
    "BV1xx411c7mD",
    "https://www.bilibili.com/video/BV1xx411c7mD",
    "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.999.0.0",
]

print("=== 测试 BV号提取 ===")
for url in test_urls:
    # 提取 BV号
    import re
    bvid = url
    if "bilibili.com" in url:
        match = re.search(r'BV[a-zA-Z0-9]+', url)
        if match:
            bvid = match.group(0)
    print(f"URL: {url}")
    print(f"BV号: {bvid}")
    print()

# 测试解析器初始化（无需登录）
print("=== 测试解析器初始化 ===")
parser = BilibiliParser()
print("✓ 解析器初始化成功")

# 测试视频信息获取（使用公开视频）
print("\n=== 测试视频信息获取 ===")
test_bvid = "BV1xx411c7mD"  # 这是一个示例BV号，可能需要替换为有效的
print(f"尝试获取视频信息: {test_bvid}")

video_info = parser.get_video_info(test_bvid)
if video_info:
    print(f"✓ 视频信息获取成功")
    print(f"  标题: {video_info.get('title', 'N/A')}")
    print(f"  作者: {video_info.get('owner', {}).get('name', 'N/A')}")
    print(f"  时长: {video_info.get('duration', 0)}秒")
    print(f"  CID: {video_info.get('cid', 0)}")
else:
    print(f"✗ 视频信息获取失败（可能是视频不存在或需要登录）")

print("\n=== 测试完成 ===")
print("注意：完整的视频解析（字幕/ASR）需要有效的B站登录凭证")
