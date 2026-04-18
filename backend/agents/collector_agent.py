"""
agents/collector_agent.py
Collector Agent - 拉取 + 解析 + 入库
按 media_type 路由到对应解析器
"""

import logging
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import RawContent
from platforms.base_connector import BasePlatformConnector, AuthError
from tools.mcp_tools import add_memory
from tools.llm import get_llm_client

logger = logging.getLogger(__name__)

# 增量同步时间戳缓存（内存级，重启后从 DB 重建）
_last_sync_at: Dict[str, datetime] = {}

# ── 进度回调类型 ────────────────────────────────────────────────────────────
# progress_callback(step, current, total, message)
# step: "fetching" | "parsing" | "storing" | "completed" | "error"


def _emit_progress(
    callback: Optional[Callable],
    step: str,
    current: int = 0,
    total: int = 0,
    message: str = "",
):
    """
    线程安全地调用进度回调。
    如果回调是异步的（协程），用 call_soon_threadsafe 安全调度到事件循环。
    如果回调是普通函数，直接调用。
    """
    if not callback:
        return
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        # 在事件循环线程中调度
        loop.call_soon_threadsafe(lambda: callback(step, current, total, message))
    except RuntimeError:
        # 没有运行中的事件循环（比如在同步上下文中），直接调用
        try:
            callback(step, current, total, message)
        except Exception:
            pass
    except Exception:
        pass


def _get_connector(platform: str) -> Optional[BasePlatformConnector]:
    """按平台 ID 获取对应连接器"""
    connector_map = {
        "pocket": "platforms.pocket_connector.PocketConnector",
        "youtube": "platforms.youtube_connector.YouTubeConnector",
        "twitter": "platforms.twitter_connector.TwitterConnector",
        "github": "platforms.github_connector.GitHubConnector",
        "bilibili": "platforms.bilibili_connector.BilibiliConnector",
        "douyin": "platforms.douyin_connector.DouyinConnector",
        "wechat": "platforms.wechat_connector.WeChatConnector",
        "xiaohongshu": "platforms.xiaohongshu_connector.XiaohongshuConnector",
    }

    class_path = connector_map.get(platform)
    if not class_path:
        logger.warning(f"[Collector] 未知平台: {platform}")
        return None

    try:
        module_path, class_name = class_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)()
    except Exception as e:
        logger.error(f"[Collector] 连接器加载失败 {platform}: {e}")
        return None


_media_router = None


def _get_media_router():
    """获取 MediaRouter 单例"""
    global _media_router
    if _media_router is None:
        from parsers.media_router import MediaRouter
        from parsers.bilibili_parser import BilibiliParser
        from parsers.youtube_parser import YouTubeMediaParser
        from parsers.audio_parser import AudioMediaParser

        router = MediaRouter()
        router.register_parser(BilibiliParser())
        router.register_parser(YouTubeMediaParser())
        router.register_parser(AudioMediaParser())
        _media_router = router
    return _media_router


def _parse_content(content: RawContent, llm_func=None, user_id: str = "") -> RawContent:
    """
    按 media_type 路由到对应解析器，丰富 body 字段
    解析路由层 + 统一文本出口
    """
    media_type = content.media_type

    # 文本/网页：提取主体正文
    if media_type == "text":
        if content.url and (not content.body or len(content.body) < 200):
            try:
                from parsers.text_parser import parse_webpage
                parsed = parse_webpage(content.url, fallback_content=content.body)
                if parsed and len(parsed) > len(content.body or ""):
                    content.body = parsed
            except Exception as e:
                logger.debug(f"[Collector] 网页解析失败: {e}")

    # 音视频：使用 MediaRouter (subtitle → ASR)
    elif media_type in ("video", "audio"):
        if content.url:
            try:
                router = _get_media_router()
                result = router.route(
                    url=content.url,
                    media_type=content.media_type,
                    platform=content.platform,
                    credentials=None,
                    bookmarked_at=content.bookmarked_at,
                )
                if result and result.transcript:
                    content.body = result.transcript[:5000]
                    logger.info(f"[Collector] MediaRouter 解析成功: platform={content.platform}, "
                               f"source={result.source}, len={len(result.transcript)}")
            except Exception as e:
                logger.warning(f"[Collector] MediaRouter 解析失败: {e}")

    # 图片（小红书等）：Qwen2-VL 图像理解
    elif media_type == "image":
        if content.thumbnail_url and not content.body:
            try:
                from parsers.vision_parser import describe_image
                desc = describe_image(content.thumbnail_url)
                if desc:
                    content.body = desc
            except Exception as e:
                logger.debug(f"[Collector] 图像理解失败: {e}")

    # 代码仓库：README 已在 Connector 中提取，这里做 Markdown 解析
    elif media_type == "repo":
        if content.body:
            try:
                from parsers.text_parser import parse_markdown
                parsed = parse_markdown(content.body)
                if parsed:
                    content.body = parsed[:5000]
            except Exception as e:
                logger.debug(f"[Collector] Markdown 解析失败: {e}")

    # PDF
    elif media_type == "pdf":
        if content.url:
            try:
                from parsers.pdf_parser import parse_pdf
                result = parse_pdf(content.url)
                if result.get("text"):
                    content.body = result["text"][:5000]
                    if result.get("title") and not content.title:
                        content.title = result["title"]
            except Exception as e:
                logger.debug(f"[Collector] PDF 解析失败: {e}")

    return content


class CollectorAgent:
    """
    Collector Agent
    职责：拉取各平台收藏 → 解析内容 → 通过 MCP 工具入库
    与其他 Agent 通信必须通过 MCP 工具接口（原则 3）
    """

    def __init__(self):
        self._llm = get_llm_client()

    def sync_single_platform(
        self,
        platform: str,
        user_id: str,
        full_sync: bool = False,
        folder_ids: Optional[List[int]] = None,
        item_ids: Optional[List[str]] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        同步单个平台
        返回同步结果统计
        user_id: 用于数据隔离，如果为None则从上下文获取
        progress_callback: 可选回调，签名: callback(step, current, total, message)
        """
        _emit_progress(progress_callback, "fetching", message=f"开始同步 {platform}...")
        logger.info(f"[Collector] 开始同步平台: {platform} (full_sync={full_sync})")

        result = {
            "platform": platform,
            "success": False,
            "added": 0,
            "skipped": 0,
            "errors": 0,
            "error_msg": "",
        }

        connector = _get_connector(platform)
        if not connector:
            result["error_msg"] = f"平台 {platform} 不支持"
            return result

        # 增量同步起点
        since = None
        if not full_sync and platform in _last_sync_at:
            since = _last_sync_at[platform]

        try:
            raw_contents = connector.fetch_all_with_content(
                since=since,
                limit=config.SYNC_BATCH_SIZE,
            )
        except AuthError as e:
            result["error_msg"] = f"认证失败: {e}"
            logger.warning(f"[Collector] {platform} 认证失败（跳过）: {e}")
            _emit_progress(progress_callback, "error", message=f"认证失败: {e}")
            return result
        except Exception as e:
            result["error_msg"] = str(e)
            logger.error(f"[Collector] {platform} 同步异常: {e}")
            _emit_progress(progress_callback, "error", message=f"同步异常: {e}")
            return result

        _emit_progress(progress_callback, "fetching", total=len(raw_contents), message=f"获取到 {len(raw_contents)} 条收藏")

        # 解析 + 入库（批量并行处理）
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from memory.memory_store import get_memory_store

        store = get_memory_store(user_id)

        # 预先过滤已存在的记忆（避免浪费 LLM 调用）
        new_contents = []
        skipped_already_exists = 0
        for content in raw_contents:
            if store.exists_by_platform_id(content.platform, content.platform_id):
                skipped_already_exists += 1
            else:
                new_contents.append(content)

        logger.info(f"[Collector] 预检查: 已存在跳过 {skipped_already_exists} 条，待处理 {len(new_contents)} 条")

        if not new_contents:
            result["skipped"] = skipped_already_exists
            result["success"] = True
            return result

        def parse_and_enqueue(content, llm_func, user_id):
            """解析单个内容，返回用于批量入库的 RawContent"""
            try:
                return _parse_content(content, llm_func=llm_func, user_id=user_id)
            except Exception as e:
                logger.warning(f"[Collector] 解析失败 {content.platform_id}: {e}")
                return None

        # 并行解析内容
        logger.info(f"[Collector] 开始并行解析 {len(new_contents)} 条内容...")
        _emit_progress(progress_callback, "parsing", total=len(new_contents), message=f"开始解析 {len(new_contents)} 条内容...")
        parsed_contents = []
        parsed_count = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(parse_and_enqueue, c, self._llm, user_id): c for c in new_contents}
            for future in as_completed(futures):
                parsed = future.result()
                parsed_count += 1
                if parsed:
                    parsed_contents.append(parsed)
                _emit_progress(progress_callback, "parsing", current=parsed_count, total=len(new_contents), message=f"解析中 {parsed_count}/{len(new_contents)}")

        logger.info(f"[Collector] 解析完成，{len(parsed_contents)} 条待入库")

        # 批量入库（并行 LLM + 批量 embedding）
        if parsed_contents:
            try:
                from tools.mcp_tools import add_memories_batch
                _emit_progress(progress_callback, "storing", total=len(parsed_contents), message=f"正在存储 {len(parsed_contents)} 条...")
                memory_ids = add_memories_batch(
                    parsed_contents,
                    llm_func=self._llm,
                    max_workers=4,
                )
                result["added"] = sum(1 for m in memory_ids if m)
                result["skipped"] = skipped_already_exists + (len(memory_ids) - result["added"])
            except Exception as e:
                logger.warning(f"[Collector] 批量入库失败，回退逐条: {e}")
                # 回退逐条处理
                for content in parsed_contents:
                    try:
                        from tools.mcp_tools import add_memory
                        memory_id = add_memory(content, llm_func=self._llm)
                        if memory_id:
                            result["added"] += 1
                        else:
                            result["skipped"] += 1
                    except Exception as e2:
                        result["errors"] += 1
                        logger.warning(f"[Collector] 入库失败: {e2}")
                result["skipped"] += skipped_already_exists

        # 更新同步时间戳
        _last_sync_at[platform] = datetime.utcnow()
        result["success"] = True

        _emit_progress(
            progress_callback, "completed",
            total=result["added"] + result["skipped"],
            message=f"完成！新增 {result['added']} 条",
        )

        logger.info(
            f"[Collector] {platform} 同步完成: "
            f"新增 {result['added']} 条，跳过 {result['skipped']} 条，失败 {result['errors']} 条"
        )
        return result

    def sync_all_platforms(self, user_id: str, full_sync: bool = False) -> List[Dict[str, Any]]:
        """
        同步所有启用的平台
        单平台失败不阻断其他平台（原则 7 推广）
        user_id: 用于数据隔离，如果为None则从上下文获取
        """
        results = []
        for platform in config.PLATFORMS_ENABLED:
            try:
                result = self.sync_single_platform(platform, user_id, full_sync=full_sync)
                results.append(result)
            except Exception as e:
                logger.error(f"[Collector] {platform} 同步崩溃（已隔离）: {e}")
                results.append({
                    "platform": platform,
                    "success": False,
                    "error_msg": str(e),
                    "added": 0, "skipped": 0, "errors": 1,
                })

        total_added = sum(r.get("added", 0) for r in results)
        logger.info(f"[Collector] 全平台同步完成，总计新增 {total_added} 条记忆")
        return results

    def resync_platform(self, platform: str, user_id: str) -> Dict[str, Any]:
        """
        重新同步指定平台
        步骤：1. 删除该平台所有已有数据 2. 执行全量同步
        user_id: 用于数据隔离
        """
        from memory.memory_store import get_memory_store, _get_db_conn

        logger.info(f"[Collector] 开始重新同步平台: {platform}")

        result = {
            "platform": platform,
            "success": False,
            "deleted": 0,
            "added": 0,
            "skipped": 0,
            "errors": 0,
            "error_msg": "",
        }

        store = get_memory_store(user_id)

        # 步骤 1: 删除该平台的现有数据
        try:
            conn = _get_db_conn(store._db_path)
            # 获取该平台的数据数量
            count_row = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE platform=?", (platform,)
            ).fetchone()
            deleted_count = count_row[0] if count_row else 0

            # 删除该平台的所有数据
            conn.execute("DELETE FROM memories WHERE platform=?", (platform,))
            conn.commit()
            result["deleted"] = deleted_count
            logger.info(f"[Collector] 已删除 {platform} 的 {deleted_count} 条数据")

            # 重建 FAISS 索引（因为 FAISS 不支持直接删除）
            # 获取剩余的所有数据
            remaining_rows = conn.execute("SELECT * FROM memories").fetchall()
            if store._index is not None:
                try:
                    import faiss
                    import numpy as np
                    # 重新创建索引
                    store._index = faiss.IndexFlatIP(store._dim)
                    store._id_to_pos.clear()
                    store._pos_to_id.clear()

                    # 重新添加剩余数据的向量
                    for row in remaining_rows:
                        memory = store._row_to_memory(row)
                        if memory.embedding:
                            vec = np.array([memory.embedding], dtype=np.float32)
                            norm = np.linalg.norm(vec, axis=1, keepdims=True)
                            if norm[0][0] > 0:
                                vec = vec / norm
                            faiss_pos = store._index.ntotal
                            store._index.add(vec)
                            store._id_to_pos[memory.id] = faiss_pos
                            store._pos_to_id[faiss_pos] = memory.id

                    store._save_index()
                    logger.info(f"[Collector] FAISS 索引已重建，剩余 {len(remaining_rows)} 条")
                except ImportError:
                    logger.warning("[Collector] faiss-cpu 未安装，跳过 FAISS 重建")

        except Exception as e:
            result["error_msg"] = f"删除数据失败: {e}"
            logger.error(f"[Collector] {platform} 删除数据失败: {e}")
            return result

        # 步骤 2: 执行全量同步（不传入 since，表示全量）
        # 清除该平台的同步时间戳，确保全量同步
        if platform in _last_sync_at:
            del _last_sync_at[platform]

        sync_result = self.sync_single_platform(platform, user_id, full_sync=True)

        # 合并结果
        result["success"] = sync_result.get("success", False)
        result["added"] = sync_result.get("added", 0)
        result["skipped"] = sync_result.get("skipped", 0)
        result["errors"] = sync_result.get("errors", 0)
        if sync_result.get("error_msg"):
            result["error_msg"] = sync_result["error_msg"]

        logger.info(
            f"[Collector] {platform} 重新同步完成: "
            f"删除 {result['deleted']} 条，新增 {result['added']} 条"
        )
        return result

    def resync_all_platforms(self, user_id: str) -> List[Dict[str, Any]]:
        """
        重新同步所有启用的平台
        步骤：1. 删除所有数据 2. 执行全量同步
        user_id: 用于数据隔离
        """
        from memory.memory_store import get_memory_store

        logger.info("[Collector] 开始重新同步所有平台")

        store = get_memory_store(user_id)

        # 步骤 1: 删除所有数据
        try:
            success = store.delete_all()
            if not success:
                return [{
                    "platform": "all",
                    "success": False,
                    "error_msg": "清空数据失败",
                    "deleted": 0, "added": 0, "skipped": 0, "errors": 1,
                }]
            logger.info("[Collector] 所有数据已清空")
        except Exception as e:
            logger.error(f"[Collector] 清空数据失败: {e}")
            return [{
                "platform": "all",
                "success": False,
                "error_msg": f"清空数据失败: {e}",
                "deleted": 0, "added": 0, "skipped": 0, "errors": 1,
            }]

        # 步骤 2: 清除所有平台的同步时间戳
        _last_sync_at.clear()

        # 步骤 3: 执行全量同步
        return self.sync_all_platforms(user_id, full_sync=True)
