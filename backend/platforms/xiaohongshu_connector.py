"""
platforms/xiaohongshu_connector.py
小红书平台连接器 - Cookie 模式（无官方 API）
Cookie 有效期约 30 天，过期前 7 天提醒用户刷新

原则（原则 7）：Cookie 失效属于预期内正常情况，
必须捕获异常并返回 needs_reauth，不能抛出异常中断整体同步
"""

import logging
import requests
import json
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import RawBookmark, RawContent
from platforms.base_connector import BasePlatformConnector, AuthError
from auth.token_store import get_token_store, TokenData

logger = logging.getLogger(__name__)

XHS_BASE = "https://www.xiaohongshu.com"
XHS_API = "https://www.xiaohongshu.com/api/sns/v10"

# 请求头模拟浏览器
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
}

COOKIE_EXPIRE_DAYS = 30


class XiaohongshuConnector(BasePlatformConnector):
    """
    小红书连接器 - Cookie 模式
    认证失效时返回 needs_reauth 状态，不抛出异常（原则 7）
    """

    def __init__(self, user_id: str = ""):
        self._store = get_token_store(user_id)
        self._cookie: Optional[str] = None
        self._session = requests.Session()

    def get_platform_id(self) -> str:
        return "xiaohongshu"

    def get_platform_name(self) -> str:
        return "小红书"

    def get_auth_mode(self) -> str:
        return "cookie"

    def get_media_type(self) -> str:
        return "image"

    def save_cookie(self, cookie: str) -> None:
        """
        保存用户提供的 Cookie
        记录保存时间，用于计算过期提醒
        """
        expires_at = (datetime.utcnow() + timedelta(days=COOKIE_EXPIRE_DAYS)).isoformat()
        self._store.save(TokenData(
            platform="xiaohongshu",
            auth_mode="cookie",
            cookie=cookie,
            expires_at=expires_at,
            last_refresh=datetime.utcnow().isoformat(),
            status="connected",
        ))
        self._cookie = cookie
        logger.info("[小红书] Cookie 已保存，有效期约 30 天")

    def check_cookie_expiring(self) -> bool:
        """检查 Cookie 是否即将过期（返回 True 表示需要提醒用户）"""
        token_data = self._store.load("xiaohongshu")
        if not token_data:
            return False
        return token_data.is_cookie_expiring_soon()

    def authenticate(self) -> bool:
        """加载 Cookie，优先从环境变量读取"""
        cookie = config.XIAOHONGSHU_COOKIE
        if not cookie:
            token_data = self._store.load("xiaohongshu")
            if token_data and token_data.status == "connected":
                cookie = token_data.cookie

        if not cookie:
            logger.warning("[小红书] 未配置 Cookie，跳过。请在设置页手动填入")
            return False

        # 检查是否即将过期
        token_data = self._store.load("xiaohongshu")
        if token_data and token_data.is_cookie_expiring_soon():
            logger.warning("[小红书] Cookie 即将过期，请前往设置页刷新")

        self._cookie = cookie
        self._session.headers.update(BROWSER_HEADERS)
        self._session.headers["Cookie"] = cookie
        return True

    def is_authenticated(self) -> bool:
        if self._cookie:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._cookie = None
        self._store.delete("xiaohongshu")

    def _check_auth_response(self, data: dict) -> bool:
        """检查响应是否表示 Cookie 已失效"""
        code = data.get("code", 0)
        if code in [-100, -101, 301, 401]:
            # Cookie 失效 - 原则 7：不抛出异常，更新状态
            logger.warning("[小红书] Cookie 已失效，需要用户刷新")
            self._store.mark_needs_reauth("xiaohongshu", "Cookie 已失效")
            self._cookie = None
            return False
        return True

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        """
        拉取小红书收藏笔记列表
        Cookie 失效时返回空列表并标记 needs_reauth（不抛出异常）
        """
        if not self.is_authenticated():
            # 原则 7：Cookie 模式失效属正常情况，返回空列表
            logger.warning("[小红书] 未认证，跳过同步")
            return []

        bookmarks = []
        cursor = ""

        while len(bookmarks) < limit:
            try:
                params = {
                    "num": min(20, limit),
                    "cursor": cursor,
                }
                resp = self._session.get(
                    f"{XHS_API}/user/fav/note/page",
                    params=params,
                    timeout=30,
                )

                if resp.status_code == 401 or resp.status_code == 403:
                    logger.warning("[小红书] Cookie 失效（HTTP 401/403）")
                    self._store.mark_needs_reauth("xiaohongshu", "Cookie 失效")
                    return bookmarks

                resp.raise_for_status()
                data = resp.json()

            except AuthError:
                return bookmarks
            except Exception as e:
                logger.warning(f"[小红书] fetch_bookmarks 异常（将跳过）: {e}")
                return bookmarks  # 原则 7：不中断，返回已拉取内容

            if not self._check_auth_response(data):
                return bookmarks

            notes = data.get("data", {}).get("notes", [])
            if not notes:
                break

            for note in notes:
                create_time_ms = note.get("time", 0)
                create_time = datetime.utcfromtimestamp(create_time_ms / 1000)

                if since and create_time < since:
                    return bookmarks

                note_id = note.get("id", "")
                bm = RawBookmark(
                    platform="xiaohongshu",
                    platform_id=note_id,
                    url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    title=note.get("title", note.get("desc", ""))[:100],
                    bookmarked_at=create_time,
                    raw_data=note,
                )
                bookmarks.append(bm)

            cursor = data.get("data", {}).get("cursor", "")
            if not cursor:
                break

        logger.info(f"[小红书] 拉取到 {len(bookmarks)} 条收藏笔记")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        note = bookmark.raw_data
        author = note.get("user", {})

        # 图片组
        images = note.get("image_list", [])
        thumbnail_url = images[0].get("url", "") if images else ""

        # 标签
        tags = [tag.get("name", "") for tag in note.get("tag_list", []) if tag.get("name")]

        return RawContent(
            platform="xiaohongshu",
            platform_name="小红书",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=note.get("title", note.get("desc", ""))[:100],
            body=note.get("desc", ""),
            media_type="image",
            author=author.get("nickname", ""),
            thumbnail_url=thumbnail_url,
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "tags": tags,
                "image_count": len(images),
                "like_count": note.get("liked_count", 0),
                "collect_count": note.get("collected_count", 0),
                "note_type": note.get("type", "normal"),
            },
        )
