"""
platforms/bilibili_connector.py
Bilibili 平台连接器 - 支持 OAuth 2.0 和 Cookie 两种模式
拉取：收藏夹列表及内容
"""

import logging
import requests
import time
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.memory_schema import RawBookmark, RawContent
from platforms.base_connector import BasePlatformConnector, AuthError
from auth.token_store import get_token_store
from auth.oauth_handler import get_oauth_handler

logger = logging.getLogger(__name__)

BILI_API_BASE = "https://api.bilibili.com"


class BilibiliConnector(BasePlatformConnector):

    def __init__(self, user_id: str = ""):
        self._store = get_token_store(user_id)
        self._oauth = get_oauth_handler()
        self._access_token: Optional[str] = None
        # B站专用 Cookie 字段
        self._sessdata: Optional[str] = ""
        self._bili_jct: Optional[str] = ""
        self._dedeuserid: Optional[str] = ""
        self._mid: Optional[str] = None  # 用户 UID

    def get_platform_id(self) -> str:
        return "bilibili"

    def get_platform_name(self) -> str:
        return "Bilibili"

    def get_auth_mode(self) -> str:
        """支持 oauth2 和 cookie 两种模式"""
        token_data = self._store.load("bilibili")
        if token_data:
            return token_data.auth_mode
        return "oauth2"  # 默认

    def get_media_type(self) -> str:
        return "video"

    def authenticate(self) -> bool:
        token_data = self._store.load("bilibili")
        if not token_data:
            logger.warning("[Bilibili] 未找到 token_data")
            return False

        logger.info(f"[Bilibili] auth_mode: {token_data.auth_mode}, sessdata exists: {bool(token_data.sessdata)}, cookie exists: {bool(token_data.cookie)}")

        # Cookie 模式 - 优先使用三个独立字段
        if token_data.auth_mode == "cookie":
            if token_data.sessdata:
                self._sessdata = token_data.sessdata
                self._bili_jct = token_data.bili_jct or ""
                self._dedeuserid = token_data.dedeuserid or ""
                logger.info(f"[Bilibili] 使用 sessdata 认证, dedeuserid: {self._dedeuserid}")
                return True
            elif token_data.cookie:
                # 兼容旧格式的 cookie 字符串，尝试提取各个字段
                cookie_str = token_data.cookie
                logger.info(f"[Bilibili] 使用旧 cookie 格式认证，尝试解析字段")

                # 从 cookie 字符串中提取 SESSDATA
                import re
                sessdata_match = re.search(r'SESSDATA=([^;]+)', cookie_str)
                if sessdata_match:
                    self._sessdata = sessdata_match.group(1)
                    logger.info(f"[Bilibili] 从 cookie 中提取到 SESSDATA")

                # 提取 bili_jct
                jct_match = re.search(r'bili_jct=([^;]+)', cookie_str)
                if jct_match:
                    self._bili_jct = jct_match.group(1)
                    logger.info(f"[Bilibili] 从 cookie 中提取到 bili_jct")

                # 提取 DedeUserID
                uid_match = re.search(r'DedeUserID=([^;]+)', cookie_str)
                if uid_match:
                    self._dedeuserid = uid_match.group(1)
                    logger.info(f"[Bilibili] 从 cookie 中提取到 DedeUserID: {self._dedeuserid}")

                if self._sessdata:
                    return True
                else:
                    logger.warning("[Bilibili] 无法从 cookie 中提取 SESSDATA")
                    return False

        # OAuth2 模式
        if token_data.auth_mode == "oauth2":
            token = self._oauth.ensure_valid_token("bilibili")
            if token:
                self._access_token = token
                return True

        return False

    def is_authenticated(self) -> bool:
        if self._access_token or self._sessdata:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._sessdata = ""
        self._bili_jct = ""
        self._dedeuserid = ""
        self._oauth.revoke("bilibili")

    def _headers(self) -> dict:
        """根据认证模式返回合适的请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com"
        }

        # 优先使用三个独立字段构造 Cookie
        if self._sessdata:
            cookie_parts = [f"SESSDATA={self._sessdata}"]
            if self._bili_jct:
                cookie_parts.append(f"bili_jct={self._bili_jct}")
            if self._dedeuserid:
                cookie_parts.append(f"DedeUserID={self._dedeuserid}")
            headers["Cookie"] = "; ".join(cookie_parts)

        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        return headers

    def _get_user_info(self) -> Optional[str]:
        """获取用户 MID"""
        try:
            resp = requests.get(
                f"{BILI_API_BASE}/x/member/mine",
                headers=self._headers(), timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("data", {}).get("mid", ""))
        except Exception:
            return None

    def _get_user_info_by_cookie(self) -> Optional[str]:
        """Cookie 模式下获取用户信息"""
        try:
            resp = requests.get(
                f"{BILI_API_BASE}/x/web-interface/nav",
                headers=self._headers(),
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                return str(data.get("data", {}).get("mid", ""))
        except Exception as e:
            logger.warning(f"[Bilibili] 获取用户信息失败: {e}")
        return None

    def _get_favorite_folders(self) -> List[dict]:
        """获取用户的所有收藏夹列表"""
        if not self._mid:
            return []

        try:
            resp = requests.get(
                f"{BILI_API_BASE}/x/v3/fav/folder/created/list-all",
                headers=self._headers(),
                params={"up_mid": self._mid},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                folders = data.get("data", {}).get("list", [])
                logger.info(f"[Bilibili] 获取到 {len(folders)} 个收藏夹")
                return folders
        except Exception as e:
            logger.warning(f"[Bilibili] 获取收藏夹列表失败: {e}")
        return []

    def _get_favorite_content(
        self,
        media_id: int,
        pn: int = 1,
        ps: int = 20
    ) -> dict:
        """
        获取单个收藏夹的内容

        Args:
            media_id: 收藏夹 ID
            pn: 页码
            ps: 每页数量 (最大20)

        Returns:
            {
                "info": 收藏夹信息,
                "medias": 视频列表,
                "has_more": 是否有更多
            }
        """
        try:
            resp = requests.get(
                f"{BILI_API_BASE}/x/v3/fav/resource/list",
                headers=self._headers(),
                params={
                    "media_id": media_id,
                    "pn": pn,
                    "ps": min(ps, 20),
                    "platform": "web",
                    "type": 0,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"[Bilibili] 获取收藏夹内容失败: {data.get('message')}")
                # Cookie 过期
                if data.get("code") in (-101, -401):
                    self._store.mark_needs_reauth("bilibili", "Cookie 已过期")
                    raise AuthError("Bilibili Cookie 已过期，请重新扫码登录")
                return {"info": {}, "medias": [], "has_more": False}

            return {
                "info": data.get("data", {}).get("info", {}),
                "medias": data.get("data", {}).get("medias") or [],
                "has_more": data.get("data", {}).get("has_more", False)
            }
        except Exception as e:
            logger.warning(f"[Bilibili] 获取收藏夹内容异常: {e}")
            return {"info": {}, "medias": [], "has_more": False}

    def _get_all_favorite_videos(self, media_id: int, folder_title: str = "") -> List[dict]:
        """
        获取单个收藏夹的所有视频（自动处理分页）

        Args:
            media_id: 收藏夹 ID
            folder_title: 收藏夹标题（用于日志）

        Returns:
            完整视频列表（已过滤失效视频）
        """
        all_videos = []
        pn = 1

        while True:
            result = self._get_favorite_content(media_id, pn=pn, ps=20)
            medias = result.get("medias", [])

            for media in medias:
                # 过滤失效视频
                bvid = media.get("bvid") or media.get("bv_id")
                title = media.get("title", "")

                if not bvid:
                    continue

                # attr=9 表示已失效
                attr = media.get("attr", 0)
                if attr == 9 or title in ["已失效视频", "已删除视频"]:
                    continue

                all_videos.append(media)

            if not result.get("has_more", False):
                break

            pn += 1
            # 避免请求过快
            time.sleep(0.3)

        logger.info(f"[Bilibili] 收藏夹 '{folder_title}' 获取到 {len(all_videos)} 个有效视频")
        return all_videos

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        """
        拉取用户的所有收藏夹内容

        Args:
            since: 增量同步起点，None 表示全量
            limit: 单次最大拉取量

        Returns:
            RawBookmark 列表
        """
        if not self.is_authenticated():
            raise AuthError("Bilibili 未授权")

        # Cookie 模式需要先获取用户 UID
        if not self._mid and self._sessdata:
            self._mid = self._get_user_info_by_cookie()

        if not self._mid:
            self._mid = self._get_user_info()

        if not self._mid:
            logger.warning("[Bilibili] 无法获取用户 UID")
            return []

        # 获取所有收藏夹
        folders = self._get_favorite_folders()
        if not folders:
            logger.warning("[Bilibili] 无法获取收藏夹列表")
            return []

        bookmarks = []

        # 遍历所有收藏夹获取内容
        for folder in folders:
            media_id = folder.get("id")
            folder_title = folder.get("title", "未知收藏夹")

            if not media_id:
                continue

            logger.info(f"[Bilibili] 正在获取收藏夹: {folder_title} (media_id={media_id})")

            # 获取该收藏夹的所有视频
            videos = self._get_all_favorite_videos(media_id, folder_title)

            for item in videos:
                # 解析收藏时间
                fav_time_ts = item.get("fav_time", 0)
                if fav_time_ts:
                    fav_time = datetime.utcfromtimestamp(fav_time_ts)
                else:
                    # 如果没有 fav_time，使用当前时间
                    fav_time = datetime.utcnow()

                # 增量同步：跳过早于 since 的内容
                if since and fav_time < since:
                    continue

                bm = RawBookmark(
                    platform="bilibili",
                    platform_id=str(item.get("id", "")),
                    url=f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    title=item.get("title", ""),
                    bookmarked_at=fav_time,
                    raw_data=item,
                )
                bookmarks.append(bm)

                if len(bookmarks) >= limit:
                    logger.info(f"[Bilibili] 已达到限制数量 {limit}，停止拉取")
                    break

            if len(bookmarks) >= limit:
                break

            # 收藏夹之间也稍作延迟
            time.sleep(0.2)

        logger.info(f"[Bilibili] 共拉取到 {len(bookmarks)} 条收藏")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        """
        将 RawBookmark 转换为 RawContent

        对于B站，由于 fetch_bookmarks 已经获取了完整信息，
        这里主要是进行数据规范化
        """
        item = bookmark.raw_data
        upper = item.get("upper", {})

        # 构建视频简介（使用 intro 字段，如果没有则使用标题）
        body = item.get("intro", "")
        if not body:
            body = item.get("title", "")

        return RawContent(
            platform="bilibili",
            platform_name="Bilibili",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=item.get("title", ""),
            body=body,
            media_type="video",
            author=upper.get("name", ""),
            thumbnail_url=item.get("cover", ""),
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "bvid": item.get("bvid", ""),
                "duration": item.get("duration", 0),
                "view": item.get("cnt_info", {}).get("play", 0),
                "danmaku": item.get("cnt_info", {}).get("danmaku", 0),
                "type": item.get("type", 2),
                "folder_name": item.get("folder_name", ""),  # 收藏夹名称（如果有）
            },
        )
