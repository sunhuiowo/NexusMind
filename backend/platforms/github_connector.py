"""
platforms/github_connector.py
GitHub 平台连接器 - OAuth 2.0 / PAT
拉取：Star 仓库列表，提取 README
"""

import logging
import requests
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import RawBookmark, RawContent
from platforms.base_connector import BasePlatformConnector, AuthError, RateLimitError
from auth.token_store import get_token_store, TokenData
from auth.oauth_handler import get_oauth_handler

logger = logging.getLogger(__name__)

GH_API_BASE = "https://api.github.com"


class GitHubConnector(BasePlatformConnector):

    def __init__(self, user_id: str = ""):
        self._store = get_token_store(user_id)
        self._oauth = get_oauth_handler()
        self._access_token: Optional[str] = None

    def get_platform_id(self) -> str:
        return "github"

    def get_platform_name(self) -> str:
        return "GitHub Star"

    def get_auth_mode(self) -> str:
        return "oauth2"

    def get_media_type(self) -> str:
        return "repo"

    def authenticate(self) -> bool:
        # 优先 PAT
        if config.GITHUB_PAT:
            self._access_token = config.GITHUB_PAT
            # 保存 PAT 到 store
            td = self._store.load("github")
            if not td:
                self._store.save(TokenData(
                    platform="github",
                    auth_mode="pat",
                    access_token=config.GITHUB_PAT,
                    status="connected",
                ))
            return True

        token = self._oauth.ensure_valid_token("github")
        if token:
            self._access_token = token
            return True
        return False

    def is_authenticated(self) -> bool:
        if self._access_token:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._oauth.revoke("github")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.is_authenticated():
            raise AuthError("GitHub 未授权")
        resp = requests.get(
            f"{GH_API_BASE}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        if resp.status_code == 401:
            self._store.mark_needs_reauth("github", "token 失效")
            raise AuthError("GitHub token 已失效")
        if resp.status_code == 403:
            raise RateLimitError("GitHub API 限速")
        resp.raise_for_status()
        return resp.json()

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        bookmarks = []
        page = 1
        per_page = min(100, limit)

        while len(bookmarks) < limit:
            try:
                repos = self._get("/user/starred", {
                    "sort": "created",
                    "direction": "desc",
                    "per_page": per_page,
                    "page": page,
                })
            except Exception as e:
                logger.warning(f"[GitHub] fetch_bookmarks 失败: {e}")
                break

            if not repos:
                break

            for repo in repos:
                starred_at_str = repo.get("starred_at", "") or repo.get("created_at", "")
                try:
                    starred_at = datetime.fromisoformat(starred_at_str.replace("Z", "+00:00"))
                    starred_at = starred_at.replace(tzinfo=None)
                except Exception:
                    starred_at = datetime.utcnow()

                if since and starred_at < since:
                    return bookmarks  # 已过截止时间，停止

                bm = RawBookmark(
                    platform="github",
                    platform_id=str(repo.get("id", "")),
                    url=repo.get("html_url", ""),
                    title=repo.get("full_name", ""),
                    bookmarked_at=starred_at,
                    raw_data=repo,
                )
                bookmarks.append(bm)

                if len(bookmarks) >= limit:
                    break

            if len(repos) < per_page:
                break
            page += 1

        logger.info(f"[GitHub] 拉取到 {len(bookmarks)} 个 Star 仓库")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        repo = bookmark.raw_data
        full_name = repo.get("full_name", "")

        # 获取 README
        readme_text = ""
        try:
            readme_data = self._get(f"/repos/{full_name}/readme")
            import base64
            content_b64 = readme_data.get("content", "")
            if content_b64:
                readme_text = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
                readme_text = readme_text[:3000]  # 限制长度
        except Exception:
            readme_text = repo.get("description", "")

        body = readme_text or repo.get("description", "")

        owner = repo.get("owner", {})

        return RawContent(
            platform="github",
            platform_name="GitHub Star",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=full_name,
            body=body,
            media_type="repo",
            author=owner.get("login", ""),
            thumbnail_url=owner.get("avatar_url", ""),
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "description": repo.get("description", ""),
                "language": repo.get("language", ""),
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "topics": repo.get("topics", []),
                "license": (repo.get("license") or {}).get("name", ""),
            },
        )
