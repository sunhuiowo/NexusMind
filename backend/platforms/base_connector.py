"""
platforms/base_connector.py
BasePlatformConnector 抽象类
所有平台连接器必须继承此类并实现全部抽象方法
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.memory_schema import RawBookmark, RawContent

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """连接器通用异常"""
    pass


class AuthError(ConnectorError):
    """认证失败异常 - Cookie 模式平台应返回此异常而非中断流程"""
    pass


class RateLimitError(ConnectorError):
    """API 限速异常"""
    pass


class BasePlatformConnector(ABC):
    """
    平台连接器抽象基类
    所有平台连接器继承此类，Collector Agent 对各平台完全透明
    新增平台只需实现此类
    """

    # ── 认证 ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def authenticate(self) -> bool:
        """
        验证 / 刷新凭证
        返回 True 表示认证有效，False 表示需要重新授权
        """
        ...

    @abstractmethod
    def is_authenticated(self) -> bool:
        """当前凭证是否有效"""
        ...

    @abstractmethod
    def revoke(self) -> None:
        """撤销授权，删除本地凭证"""
        ...

    # ── 数据拉取 ───────────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        """
        拉取收藏书签列表（轻量，不含完整内容）
        since: 增量同步起点，None 表示全量
        limit: 单次最大拉取量
        """
        ...

    @abstractmethod
    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        """
        拉取单条内容详情，normalize 为 RawContent
        """
        ...

    # ── 平台信息 ───────────────────────────────────────────────────────────────

    @abstractmethod
    def get_platform_id(self) -> str:
        """平台 ID，小写，如 'youtube' / 'github'"""
        ...

    @abstractmethod
    def get_platform_name(self) -> str:
        """平台显示名，如 'YouTube' / 'GitHub'"""
        ...

    @abstractmethod
    def get_auth_mode(self) -> str:
        """认证模式：'oauth2' / 'apikey' / 'cookie' / 'pat'"""
        ...

    # ── 默认实现（可按需覆盖）─────────────────────────────────────────────────

    def get_media_type(self) -> str:
        """平台默认媒体类型，子类可覆盖"""
        return "text"

    def fetch_all_with_content(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawContent]:
        """
        拉取书签列表并补全内容详情
        默认实现：循环调用 fetch_bookmarks + fetch_content
        高频 API 的平台可覆盖此方法实现批量请求
        """
        if not self.is_authenticated():
            if not self.authenticate():
                raise AuthError(f"{self.get_platform_name()} 认证失败，请重新授权")

        bookmarks = self.fetch_bookmarks(since=since, limit=limit)
        contents = []

        for bm in bookmarks:
            try:
                content = self.fetch_content(bm)
                contents.append(content)
            except Exception as e:
                logger.warning(
                    f"[{self.get_platform_id()}] 拉取内容失败 {bm.platform_id}: {e}"
                )
                # 单条失败不阻断整体
                continue

        return contents

    def validate_raw_content(self, content: RawContent) -> bool:
        """
        验证 RawContent 是否符合规范
        用于集成测试，确保 normalize() 输出完整
        """
        required_fields = [
            "platform", "platform_name", "platform_id",
            "url", "title", "media_type"
        ]
        for f in required_fields:
            val = getattr(content, f, None)
            if not val:
                logger.error(f"[{self.get_platform_id()}] RawContent 缺失字段: {f}")
                return False
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.get_platform_id()} auth={self.get_auth_mode()}>"
