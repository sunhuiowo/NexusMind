"""
parsers/bilibili_parser.py
B站视频解析器 - 音频获取 + ASR + 字幕获取
参考 bilibili-rag 实现
"""

import os
import re
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from urllib.parse import urlencode

import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from parsers.audio_parser import transcribe_audio, format_transcript_with_timestamps

logger = logging.getLogger(__name__)

BILI_API_BASE = "https://api.bilibili.com"


@dataclass
class BilibiliVideoContent:
    """B站视频内容解析结果"""
    bvid: str
    title: str
    description: str = ""
    transcript: str = ""  # ASR 转录文本或字幕
    transcript_source: str = ""  # "asr" | "subtitle" | "description"
    duration: int = 0
    author: str = ""
    thumbnail: str = ""
    cid: int = 0
    view_count: int = 0
    danmaku_count: int = 0


class BilibiliParser:
    """B站视频解析器 - 获取音频/字幕并转录"""

    def __init__(self, sessdata: str = None, bili_jct: str = None, dedeuserid: str = None):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.dedeuserid = dedeuserid
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com"
        })

    def _get_cookies(self) -> Dict[str, str]:
        """获取 Cookie 字典"""
        cookies = {}
        if self.sessdata:
            cookies["SESSDATA"] = self.sessdata
        if self.bili_jct:
            cookies["bili_jct"] = self.bili_jct
        if self.dedeuserid:
            cookies["DedeUserID"] = self.dedeuserid
        return cookies

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = dict(self.session.headers)
        if self.sessdata:
            cookie_parts = [f"SESSDATA={self.sessdata}"]
            if self.bili_jct:
                cookie_parts.append(f"bili_jct={self.bili_jct}")
            if self.dedeuserid:
                cookie_parts.append(f"DedeUserID={self.dedeuserid}")
            headers["Cookie"] = "; ".join(cookie_parts)
        return headers

    def get_video_info(self, bvid: str) -> Optional[Dict[str, Any]]:
        """获取视频基本信息"""
        try:
            resp = self.session.get(
                f"{BILI_API_BASE}/x/web-interface/view",
                params={"bvid": bvid},
                headers=self._get_headers(),
                timeout=30
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {})
        except Exception as e:
            logger.warning(f"[BilibiliParser] 获取视频信息失败 [{bvid}]: {e}")
        return None

    def get_video_pages(self, bvid: str) -> List[Dict[str, Any]]:
        """获取视频分P信息"""
        video_info = self.get_video_info(bvid)
        if video_info:
            return video_info.get("pages", [])
        return []

    def get_player_info(self, bvid: str, cid: int, aid: int = None) -> Optional[Dict[str, Any]]:
        """获取播放器信息（包含字幕）"""
        params = {"bvid": bvid, "cid": cid}
        if aid:
            params["aid"] = aid

        try:
            # 尝试 WBI 接口
            resp = self.session.get(
                f"{BILI_API_BASE}/x/player/wbi/v2",
                params=params,
                headers=self._get_headers(),
                timeout=30
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {})

            # 回退到普通接口
            resp = self.session.get(
                f"{BILI_API_BASE}/x/player/v2",
                params=params,
                headers=self._get_headers(),
                timeout=30
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {})
        except Exception as e:
            logger.warning(f"[BilibiliParser] 获取播放器信息失败 [{bvid}]: {e}")
        return None

    def get_audio_url(self, bvid: str, cid: int) -> Optional[str]:
        """获取音频流 URL"""
        params = {
            "bvid": bvid,
            "cid": cid,
            "fnval": 16,
            "fnver": 0,
            "fourk": 1,
        }

        try:
            # 尝试 WBI 接口
            resp = self.session.get(
                f"{BILI_API_BASE}/x/player/wbi/playurl",
                params=params,
                headers=self._get_headers(),
                cookies=self._get_cookies(),
                timeout=30
            )
            data = resp.json()

            if data.get("code") != 0:
                # 回退到普通接口
                resp = self.session.get(
                    f"{BILI_API_BASE}/x/player/playurl",
                    params=params,
                    headers=self._get_headers(),
                    cookies=self._get_cookies(),
                    timeout=30
                )
                data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"[BilibiliParser] 获取音频 URL 失败 [{bvid}]: {data.get('message')}")
                return None

            payload = data.get("data", {})
            dash = payload.get("dash", {})
            audio_list = dash.get("audio", [])

            if audio_list:
                # 选择音质合适的音频
                def get_bandwidth(item):
                    bw = item.get("bandwidth") or item.get("bandWidth") or 0
                    try:
                        return int(bw)
                    except:
                        return 0

                # 优先选择 <= 96kbps 的最高档
                max_bw = 96000
                candidates = [a for a in audio_list if get_bandwidth(a) > 0]
                if candidates:
                    preferred = [a for a in candidates if get_bandwidth(a) <= max_bw]
                    if preferred:
                        best = max(preferred, key=get_bandwidth)
                    else:
                        best = min(candidates, key=get_bandwidth)
                else:
                    best = audio_list[0]
                return best.get("baseUrl") or best.get("base_url") or best.get("url")

            # 尝试 durl
            durl = payload.get("durl", [])
            if durl:
                return durl[0].get("url")

        except Exception as e:
            logger.warning(f"[BilibiliParser] 获取音频 URL 异常 [{bvid}]: {e}")
        return None

    def download_subtitle(self, subtitle_url: str) -> str:
        """下载并解析字幕文件"""
        try:
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url

            resp = self.session.get(subtitle_url, timeout=30)
            data = resp.json()

            texts = []
            for item in data.get("body", []):
                content = item.get("content", "")
                if content:
                    texts.append(content)

            return "\n".join(texts)
        except Exception as e:
            logger.warning(f"[BilibiliParser] 下载字幕失败: {e}")
            return ""

    def get_subtitle(self, bvid: str, cid: int, video_info: Dict = None) -> Optional[str]:
        """获取视频字幕（优先中文字幕）"""
        def pick_subtitle(subtitles: list) -> Optional[dict]:
            """优先选中文且人工字幕，没有就回退到中文自动字幕"""
            if not subtitles:
                return None

            def is_zh(sub):
                lan = sub.get("lan", "") or ""
                return "zh" in lan.lower() or "cn" in lan.lower()

            # 优先人工字幕
            for sub in subtitles:
                if is_zh(sub) and str(sub.get("ai_status", "0")) == "0":
                    return sub

            # 其次自动字幕
            for sub in subtitles:
                if is_zh(sub):
                    return sub

            # 最后选第一个
            return subtitles[0] if subtitles else None

        def extract_subtitles(data: dict) -> list:
            if not data:
                return []
            subtitle_block = data.get("subtitle", {}) or {}
            return subtitle_block.get("subtitles") or subtitle_block.get("list") or []

        # 获取播放器信息
        aid = video_info.get("aid") if video_info else None
        player_info = self.get_player_info(bvid, cid, aid)

        subtitles = extract_subtitles(player_info)
        if not subtitles and video_info:
            # 尝试从 video_info 获取
            subtitles = video_info.get("subtitle", {}).get("list", [])

        if subtitles:
            selected = pick_subtitle(subtitles)
            if selected:
                subtitle_url = selected.get("subtitle_url") or selected.get("url", "")
                if subtitle_url:
                    subtitle_text = self.download_subtitle(subtitle_url)
                    if subtitle_text and len(subtitle_text) >= 50:
                        logger.info(f"[BilibiliParser] 字幕获取成功 [{bvid}]，长度={len(subtitle_text)}")
                        return subtitle_text

        return None

    def download_audio(self, audio_url: str, output_path: str) -> bool:
        """下载音频到本地"""
        if not audio_url:
            return False

        try:
            headers = self._get_headers()
            resp = self.session.get(
                audio_url,
                headers=headers,
                stream=True,
                timeout=120
            )

            if resp.status_code not in (200, 206):
                logger.warning(f"[BilibiliParser] 下载音频失败: status={resp.status_code}")
                return False

            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return os.path.exists(output_path) and os.path.getsize(output_path) > 1024
        except Exception as e:
            logger.warning(f"[BilibiliParser] 下载音频异常: {e}")
            return False

    def parse_video(self, bvid: str, cid: int = None, title: str = None) -> BilibiliVideoContent:
        """
        解析B站视频内容
        策略：字幕 > ASR > 简介
        """
        # 获取视频信息
        video_info = self.get_video_info(bvid)
        if not video_info:
            return BilibiliVideoContent(
                bvid=bvid,
                title=title or bvid,
                description="无法获取视频信息",
                transcript_source="error"
            )

        # 提取基本信息
        if not cid:
            cid = video_info.get("cid", 0)
        if not title:
            title = video_info.get("title", "")

        description = video_info.get("desc", "")
        duration = video_info.get("duration", 0)
        owner = video_info.get("owner", {})
        author = owner.get("name", "")
        thumbnail = video_info.get("pic", "")
        stat = video_info.get("stat", {})
        view_count = stat.get("view", 0)
        danmaku_count = stat.get("danmaku", 0)

        transcript = ""
        transcript_source = ""

        # Level 1: 尝试获取字幕
        logger.info(f"[BilibiliParser] 尝试获取字幕 [{bvid}]...")
        subtitle_text = self.get_subtitle(bvid, cid, video_info)
        if subtitle_text and len(subtitle_text) >= 50:
            transcript = subtitle_text
            transcript_source = "subtitle"
            logger.info(f"[BilibiliParser] 使用字幕 [{bvid}]，长度={len(transcript)}")
        else:
            # Level 2: ASR 音频转录（可选，默认禁用以避免内存问题）
            asr_enabled = getattr(config, 'BILIBILI_ASR_ENABLED', False)
            if asr_enabled:
                logger.info(f"[BilibiliParser] 尝试 ASR [{bvid}]...")
                try:
                    audio_url = self.get_audio_url(bvid, cid)
                    if audio_url:
                        with tempfile.TemporaryDirectory() as tmp_dir:
                            audio_path = os.path.join(tmp_dir, f"{bvid}_audio.m4s")
                            if self.download_audio(audio_url, audio_path):
                                asr_result = transcribe_audio(audio_path, return_timestamps=True)
                                asr_text = asr_result.get("text", "")
                                if asr_text and len(asr_text) >= 50:
                                    transcript = asr_text
                                    transcript_source = "asr"
                                    logger.info(f"[BilibiliParser] ASR 成功 [{bvid}]，长度={len(transcript)}")
                except Exception as e:
                    logger.warning(f"[BilibiliParser] ASR 失败 [{bvid}]: {e}")
            else:
                logger.info(f"[BilibiliParser] ASR 已禁用，跳过音频转录 [{bvid}]")

            # Level 3: 使用简介兜底
            if not transcript:
                transcript = description
                transcript_source = "description"
                logger.info(f"[BilibiliParser] 使用简介 [{bvid}]")

        return BilibiliVideoContent(
            bvid=bvid,
            title=title,
            description=description,
            transcript=transcript,
            transcript_source=transcript_source,
            duration=duration,
            author=author,
            thumbnail=thumbnail,
            cid=cid,
            view_count=view_count,
            danmaku_count=danmaku_count
        )


def parse_bilibili_video(
    url_or_bvid: str,
    sessdata: str = None,
    bili_jct: str = None,
    dedeuserid: str = None
) -> Dict[str, Any]:
    """
    解析B站视频的便捷函数

    Args:
        url_or_bvid: 视频URL或BV号
        sessdata: B站登录凭证
        bili_jct: B站csrf token
        dedeuserid: B站用户ID

    Returns:
        {
            "title": "",
            "content": "",  # 转录文本或简介
            "author": "",
            "thumbnail": "",
            "duration": 0,
            "source": "subtitle|asr|description",
            "bvid": "",
            "cid": 0
        }
    """
    # 提取 BV号
    bvid = url_or_bvid
    if "bilibili.com" in url_or_bvid:
        match = re.search(r'BV[a-zA-Z0-9]+', url_or_bvid)
        if match:
            bvid = match.group(0)

    if not bvid or not bvid.startswith("BV"):
        logger.error(f"[BilibiliParser] 无效的BV号: {url_or_bvid}")
        return {
            "title": "",
            "content": "无效的BV号",
            "author": "",
            "thumbnail": "",
            "duration": 0,
            "source": "error",
            "bvid": url_or_bvid,
            "cid": 0
        }

    parser = BilibiliParser(sessdata, bili_jct, dedeuserid)
    result = parser.parse_video(bvid)

    return {
        "title": result.title,
        "content": result.transcript or result.description,
        "author": result.author,
        "thumbnail": result.thumbnail,
        "duration": result.duration,
        "source": result.transcript_source,
        "bvid": result.bvid,
        "cid": result.cid
    }
