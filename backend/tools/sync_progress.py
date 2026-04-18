"""
同步进度管理器 - 支持 SSE 实时推送
线程安全，支持多用户并发同步
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Optional, AsyncGenerator
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class PlatformProgress:
    """单个平台的同步进度"""
    platform: str
    status: str = "idle"  # idle | running | done | error
    step: str = ""       # fetching | parsing | storing | completed | failed
    current: int = 0      # 当前处理到第几项
    total: int = 0       # 总共多少项
    message: str = ""     # 人类可读的状态描述
    error: str = ""
    started_at: float = 0
    updated_at: float = 0

    def to_dict(self) -> dict:
        return asdict(self)


class SyncProgressManager:
    """
    同步进度管理器（单例）

    使用方式:
        progress = SyncProgressManager()

        # 同步开始时
        progress.start(platform, total=36)

        # 同步过程中
        progress.update(platform, step="parsing", current=10, total=36, message="解析中...")

        # 同步完成
        progress.complete(platform, added=30, skipped=6, errors=0)

        # SSE 订阅
        async for event in progress.subscribe(user_id):
            yield event
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 按用户隔离的进度数据: {user_id: {platform: PlatformProgress}}
        self._progress: Dict[str, Dict[str, PlatformProgress]] = {}
        self._progress_lock = Lock()

        # SSE 订阅者: {user_id: asyncio.Queue}
        self._subscribers: Dict[str, asyncio.Queue] = {}
        self._subscribers_lock = Lock()

        # 全局轮询锁（防止 SSE 重复推送）
        self._last_emit: Dict[str, float] = {}  # key -> last emit timestamp

    def _get_user_progress(self, user_id: str) -> Dict[str, PlatformProgress]:
        with self._progress_lock:
            if user_id not in self._progress:
                self._progress[user_id] = {}
            return self._progress[user_id]

    def _emit_to_user(self, user_id: str, data: dict):
        """向指定用户的 SSE 订阅者发送事件"""
        with self._subscribers_lock:
            queue = self._subscribers.get(user_id)
        if queue is None:
            return
        try:
            queue.put_nowait(data)
        except Exception as e:
            logger.warning(f"[SyncProgress] Failed to emit to user {user_id}: {e}")

    def _broadcast_change(self, user_id: str):
        """通知 SSE 有数据变化（通过设置事件）"""
        with self._subscribers_lock:
            queue = self._subscribers.get(user_id)
        if queue is None:
            return
        try:
            queue.put_nowait({"type": "change"})
        except Exception:
            pass

    # ── 公开 API ──────────────────────────────────────────────────────────

    def start(self, user_id: str, platform: str, total: int = 0):
        """标记某个平台同步开始"""
        now = time.time()
        progress = self._get_user_progress(user_id)
        with self._progress_lock:
            progress[platform] = PlatformProgress(
                platform=platform,
                status="running",
                step="fetching",
                total=total,
                current=0,
                message="正在获取收藏夹...",
                started_at=now,
                updated_at=now,
            )
        self._broadcast_change(user_id)

    def update(
        self,
        user_id: str,
        platform: str,
        step: str,
        current: int = 0,
        total: int = 0,
        message: str = "",
    ):
        """
        更新进度

        step: fetching | parsing | storing | embedding | completed
        """
        progress = self._get_user_progress(user_id)
        now = time.time()
        with self._progress_lock:
            if platform in progress:
                p = progress[platform]
                p.status = "running"
                p.step = step
                p.current = current
                if total > 0:
                    p.total = total
                p.message = message
                p.updated_at = now

        # 发送 SSE 事件
        evt = {
            "type": "progress",
            "platform": platform,
            "step": step,
            "current": current,
            "total": progress[platform].total if platform in progress else total,
            "message": message,
        }
        self._emit_to_user(user_id, evt)

    def set_total(self, user_id: str, platform: str, total: int):
        """设置总数量（在 fetching 完成后知道总数）"""
        progress = self._get_user_progress(user_id)
        with self._progress_lock:
            if platform in progress:
                progress[platform].total = total
        self._broadcast_change(user_id)

    def complete(
        self,
        user_id: str,
        platform: str,
        added: int = 0,
        skipped: int = 0,
        errors: int = 0,
        error_msg: str = "",
    ):
        """标记同步完成"""
        progress = self._get_user_progress(user_id)
        now = time.time()
        with self._progress_lock:
            if platform in progress:
                p = progress[platform]
                p.status = "done" if not error_msg else "error"
                p.step = "completed" if not error_msg else "failed"
                p.current = p.total
                p.message = f"完成！新增 {added} 条" if not error_msg else f"失败: {error_msg}"
                p.error = error_msg
                p.updated_at = now

        evt = {
            "type": "complete",
            "platform": platform,
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "error": error_msg,
            "message": f"完成！新增 {added} 条" if not error_msg else f"失败: {error_msg}",
        }
        self._emit_to_user(user_id, evt)

    def error(self, user_id: str, platform: str, error_msg: str):
        """标记同步出错"""
        self.complete(user_id, platform, error_msg=error_msg)

    def get_all(self, user_id: str) -> Dict[str, dict]:
        """获取用户所有平台的当前进度"""
        progress = self._get_user_progress(user_id)
        with self._progress_lock:
            return {k: v.to_dict() for k, v in progress.items()}

    def clear(self, user_id: str, platform: str = None):
        """清除进度（同步完成后调用）"""
        progress = self._get_user_progress(user_id)
        with self._progress_lock:
            if platform:
                progress.pop(platform, None)
            else:
                progress.clear()
        self._broadcast_change(user_id)

    async def subscribe(self, user_id: str) -> AsyncGenerator[dict, None]:
        """
        SSE 订阅者 Generator
        持续 yield 进度更新，直到客户端断开
        """
        queue: asyncio.Queue = asyncio.Queue()

        with self._subscribers_lock:
            self._subscribers[user_id] = queue

        try:
            # 首先发送当前所有进度状态
            current = self.get_all(user_id)
            yield {"event": "init", "data": json.dumps(current, ensure_ascii=False)}

            while True:
                try:
                    # 等待事件，最多等 30 秒超时
                    evt = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if evt.get("type") == "change":
                        # 有变化，重新发送全量状态
                        current = self.get_all(user_id)
                        yield {"event": "change", "data": json.dumps(current, ensure_ascii=False)}
                    else:
                        # 单个进度事件
                        yield {"event": evt.get("type", "progress"), "data": json.dumps(evt, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    # 发送心跳保活
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            with self._subscribers_lock:
                self._subscribers.pop(user_id, None)


# 全局单例
_progress_manager: Optional[SyncProgressManager] = None


def get_progress_manager() -> SyncProgressManager:
    global _progress_manager
    if _progress_manager is None:
        _progress_manager = SyncProgressManager()
    return _progress_manager


# 便捷函数
def emit_start(user_id: str, platform: str, total: int = 0):
    get_progress_manager().start(user_id, platform, total)


def emit_update(user_id: str, platform: str, step: str, current: int = 0, total: int = 0, message: str = ""):
    get_progress_manager().update(user_id, platform, step, current, total, message)


def emit_complete(user_id: str, platform: str, added: int = 0, skipped: int = 0, errors: int = 0, error_msg: str = ""):
    get_progress_manager().complete(user_id, platform, added, skipped, errors, error_msg)


def emit_error(user_id: str, platform: str, error_msg: str):
    get_progress_manager().error(user_id, platform, error_msg)
