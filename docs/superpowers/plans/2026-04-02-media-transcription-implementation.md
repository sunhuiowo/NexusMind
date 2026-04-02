# Media Transcription Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement unified audio/video transcription during sync — subtitle-first then ASR fallback — with a `MediaParser` protocol, `MediaRouter`, and `ASRService`.

**Architecture:** Replace per-platform parsing in `collector_agent._parse_content()` with a `MediaRouter` that dispatches to registered `MediaParser` implementations. A new `ASRService` provides unified ASR access (qwen via vLLM, or whisper). YouTube parser added.

**Tech Stack:** Python, ffmpeg, qwen3-asr-1.7b (vLLM), Whisper, yt-dlp

---

## Chunk 1: Foundation — ASRService + MediaParser Protocol

### Files

- Create: `backend/tools/asr_service.py`
- Create: `backend/parsers/media_parser_protocol.py`
- Modify: `backend/config.py` (add ASR config fields)
- Test: `backend/tests/test_asr_service.py`, `backend/tests/test_media_parser_protocol.py`

---

- [ ] **Step 1: Write failing test for ASRService**

```python
# backend/tests/test_asr_service.py
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

class TestASRService:
    def test_transcribe_with_qwen_provider(self):
        """qwen provider calls ASRClient under the hood"""
        from tools.asr_service import ASRService
        svc = ASRService(provider="qwen")
        # Mock ASRClient
        with patch("tools.asr_service.get_asr_client") as mock_get:
            mock_client = MagicMock()
            mock_client.transcribe_audio.return_value = "测试转录文本"
            mock_get.return_value = mock_client
            result = svc.transcribe(Path("test.wav"), "test.wav")
            assert result == "测试转录文本"
            mock_client.transcribe_audio.assert_called_once()

    def test_transcribe_with_whisper_provider(self):
        """whisper provider calls audio_parser.transcribe_audio"""
        from tools.asr_service import ASRService
        svc = ASRService(provider="whisper")
        with patch("tools.asr_service.transcribe_audio") as mock_trans:
            mock_trans.return_value = {"text": "whisper result", "segments": [], "language": ""}
            result = svc.transcribe(Path("test.wav"), "test.wav")
            assert result == "whisper result"

    def test_extract_audio_from_video(self):
        """extract_audio_from_video uses ffmpeg to extract to wav"""
        from tools.asr_service import ASRService
        svc = ASRService(provider="qwen")
        with patch("tools.asr_service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("builtins.open", MagicMock()):
                with patch("os.path.exists", return_value=True):
                    with patch("os.path.getsize", return_value=1024):
                        result = svc.extract_audio_from_video("http://example.com/video.mp4", Path("/tmp/out.wav"))
                        # Should call ffmpeg
                        mock_run.assert_called()
```

Run: `pytest backend/tests/test_asr_service.py -v`
Expected: FAIL — module doesn't exist

---

- [ ] **Step 2: Implement `ParsedMediaContent` dataclass and `MediaParser` Protocol**

```python
# backend/parsers/media_parser_protocol.py
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class ParsedMediaContent:
    """音视频解析结果"""
    transcript: str                    # 转录文本
    source: str                        # "subtitle" | "asr" | "description" | "error"
    media_type: str                    # "video" | "audio"
    language: Optional[str] = None     # 音频语言


class MediaParser(Protocol):
    """音视频解析器接口"""

    def supports(self, url: str) -> bool:
        """判断是否支持此URL"""

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        """
        解析音视频
        策略: subtitle → ASR
        Returns None if this parser doesn't support the URL or parsing failed
        """

    def get_audio_url(self, url: str, credentials: dict = None) -> Optional[str]:
        """获取音频URL（用于ASR），如果不支持返回None"""
```

Run: `pytest backend/tests/test_media_parser_protocol.py -v`
Expected: FAIL — module doesn't exist

---

- [ ] **Step 3: Write failing test for MediaRouter**

```python
# backend/tests/test_media_router.py
import pytest
from unittest.mock import patch, MagicMock
from parsers.media_router import MediaRouter
from memory.memory_schema import RawContent

class TestMediaRouter:
    def test_text_platform_skipped(self):
        """GitHub (text) → returns None, doesn't call ASR"""
        router = MediaRouter()
        # Register a mock parser
        mock_parser = MagicMock()
        mock_parser.supports.return_value = False  # No parser supports github
        router.register(mock_parser)

        content = RawContent(
            platform="github", platform_id="123", url="https://github.com/foo/bar",
            title="Test", body="readme", media_type="text",
            bookmarked_at="2024-01-01"
        )
        result = router.route(content)
        assert result is None  # text platform skipped
        mock_parser.parse.assert_not_called()  # Should not even be called

    def test_video_platform_routes_to_supporting_parser(self):
        """Video platform with supporting parser → calls parse()"""
        router = MediaRouter()
        mock_parser = MagicMock()
        mock_parser.supports.return_value = True
        from parsers.media_parser_protocol import ParsedMediaContent
        mock_parser.parse.return_value = ParsedMediaContent(
            transcript="test transcript", source="subtitle",
            media_type="video", language="zh"
        )
        router.register(mock_parser)

        content = RawContent(
            platform="bilibili", platform_id="BV123", url="https://www.bilibili.com/video/BV123",
            title="Test", body="", media_type="video",
            bookmarked_at="2024-01-01"
        )
        result = router.route(content)
        assert result is not None
        assert result.transcript == "test transcript"
        mock_parser.parse.assert_called_once()

    def test_no_supporting_parser_returns_none(self):
        """No parser supports URL → returns None gracefully"""
        router = MediaRouter()
        mock_parser = MagicMock()
        mock_parser.supports.return_value = False
        router.register(mock_parser)

        content = RawContent(
            platform="bilibili", platform_id="BV123", url="https://www.bilibili.com/video/BV123",
            title="Test", body="", media_type="video",
            bookmarked_at="2024-01-01"
        )
        result = router.route(content)
        assert result is None
```

Run: `pytest backend/tests/test_media_router.py -v`
Expected: FAIL — module doesn't exist

---

- [ ] **Step 4: Implement `ASRService` (minimal, YAGNI-compliant)**

```python
# backend/tools/asr_service.py
"""
统一 ASR 服务 - 支持 qwen (vLLM) 和 whisper provider
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ASRService:
    """
    统一 ASR 服务接口

    Provider:
    - "qwen": qwen3-asr-1.7b via vLLM API (使用 ASRClient)
    - "whisper": 本地 Whisper 推理 (使用 audio_parser.transcribe_audio)
    """

    def __init__(self, provider: str = None):
        import config as cfg
        self.provider = provider or getattr(cfg, 'ASR_PROVIDER', 'qwen')
        self._asr_client = None

    def _get_asr_client(self):
        if self._asr_client is None:
            from tools.asr import ASRClient
            self._asr_client = ASRClient()
        return self._asr_client

    def transcribe(self, audio_source: Path | str, filename: str = "audio.wav") -> str:
        """
        转录音频文件

        Args:
            audio_source: 音频文件路径 (本地文件)
            filename: 文件名（用于格式检测）
        Returns:
            转录文本
        """
        if self.provider == "whisper":
            return self._transcribe_whisper(audio_source)
        else:
            return self._transcribe_qwen(audio_source, filename)

    def _transcribe_qwen(self, audio_source: Path | str, filename: str) -> str:
        client = self._get_asr_client()
        with open(audio_source, "rb") as f:
            audio_bytes = f.read()
        return client.transcribe_audio(audio_bytes, filename)

    def _transcribe_whisper(self, audio_source: Path | str) -> str:
        from parsers.audio_parser import transcribe_audio
        result = transcribe_audio(str(audio_source), return_timestamps=False)
        return result.get("text", "")

    def transcribe_url(self, audio_url: str, filename: str = "audio.wav") -> str:
        """从URL下载并转录音频"""
        audio_bytes = self._download_audio(audio_url)
        if not audio_bytes:
            raise Exception(f"Failed to download audio from {audio_url}")
        client = self._get_asr_client()
        return client.transcribe_audio(audio_bytes, filename)

    def _download_audio(self, url: str) -> Optional[bytes]:
        """下载音频到临时文件"""
        import requests
        try:
            resp = requests.get(url, stream=True, timeout=120, headers={
                "User-Agent": "Mozilla/5.0 (compatible; PersonalAIMemory/1.0)"
            })
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning(f"[ASRService] 下载音频失败 {url}: {e}")
            return None
```

Run: `pytest backend/tests/test_asr_service.py -v`
Expected: PASS (or FAIL on specific assertions)

---

- [ ] **Step 5: Implement `MediaRouter`**

```python
# backend/parsers/media_router.py
"""
MediaRouter - 音视频解析路由层
"""
import logging
from typing import Optional
from memory.memory_schema import RawContent
from .media_parser_protocol import MediaParser, ParsedMediaContent

logger = logging.getLogger(__name__)


# 纯文本平台，跳过音视频处理
TEXT_ONLY_PLATFORMS = {"github", "wechat", "pocket"}


class MediaRouter:
    """
    音视频解析路由器

    使用方法:
        router = MediaRouter()
        router.register(BilibiliMediaParser())
        router.register(YouTubeMediaParser())
        router.register(AudioMediaParser())

        result = router.route(raw_content)
        if result:
            raw_content.body = result.transcript
    """

    def __init__(self):
        self._parsers: list[MediaParser] = []

    def register(self, parser: MediaParser) -> None:
        """注册一个 parser"""
        self._parsers.append(parser)

    def route(self, content: RawContent, llm_func=None) -> Optional[ParsedMediaContent]:
        """
        路由 RawContent 到对应的 Parser 解析

        逻辑:
        - media_type == "text" → 直接跳过，返回 None
        - 纯文本平台 → 直接跳过，返回 None
        - 其他 → 找到支持该 URL 的 parser，调用其 parse()

        Args:
            content: RawContent 对象
            llm_func: 可选，LLM 函数（用于某些需要LLM的parser）

        Returns:
            ParsedMediaContent 如果解析成功
            None 如果不需要/无法解析
        """
        media_type = content.media_type

        # 文本类型不需要音视频处理
        if media_type == "text":
            return None

        # 纯文本平台直接跳过
        if content.platform in TEXT_ONLY_PLATFORMS:
            return None

        # ASR 全局开关
        import config as cfg
        if not getattr(cfg, 'SYNC_ASR_ENABLED', True):
            return None

        # 检查平台级别 ASR 开关
        platform_asr_key = f"{content.platform.upper()}_ASR_ENABLED"
        if hasattr(cfg, platform_asr_key) and not getattr(cfg, platform_asr_key, True):
            return None

        # 日期窗口过滤：只处理最近 N 天内的收藏
        recent_days = getattr(cfg, 'SYNC_RECENT_WINDOW_DAYS', 90)
        if recent_days > 0 and content.bookmarked_at:
            from datetime import datetime, timedelta
            try:
                bookmarked = datetime.fromisoformat(content.bookmarked_at.replace('Z', '+00:00'))
                cutoff = datetime.utcnow() - timedelta(days=recent_days)
                if bookmarked < cutoff:
                    logger.debug(f"[MediaRouter] 跳过早期收藏: {content.platform_id} ({content.bookmarked_at})")
                    return None
            except Exception:
                pass  # 日期解析失败，不跳过

        # 音视频平台，找到对应 parser
        for parser in self._parsers:
            if parser.supports(content.url):
                try:
                    credentials = self._get_credentials(content.platform)
                    result = parser.parse(content.url, media_type, credentials)
                    if result and result.transcript:
                        logger.info(
                            f"[MediaRouter] {content.platform} 解析成功: "
                            f"source={result.source}, len={len(result.transcript)}"
                        )
                        return result
                except Exception as e:
                    logger.warning(f"[MediaRouter] {parser.__class__.__name__} 解析失败: {e}")

        # 没有找到合适的 parser
        logger.debug(f"[MediaRouter] 无可用 parser for {content.url}")
        return None

    def _get_credentials(self, platform: str) -> dict:
        """获取平台认证信息"""
        try:
            from auth.token_store import get_token_store
            store = get_token_store()
            token_data = store.load(platform)
            if not token_data:
                return {}
            creds = {}
            if hasattr(token_data, 'cookie') and token_data.cookie:
                creds['cookie'] = token_data.cookie
            if hasattr(token_data, 'sessdata') and token_data.sessdata:
                creds['sessdata'] = token_data.sessdata
            if hasattr(token_data, 'bili_jct') and token_data.bili_jct:
                creds['bili_jct'] = token_data.bili_jct
            if hasattr(token_data, 'dedeuserid') and token_data.dedeuserid:
                creds['dedeuserid'] = token_data.dedeuserid
            return creds
        except Exception:
            return {}
```

Run: `pytest backend/tests/test_media_router.py -v`

---

- [ ] **Step 6: Add ASR config to config.py**

Modify `backend/config.py`:

1. Add to `get_all_config()`:
```python
("SYNC_ASR_ENABLED", True),
("SYNC_RECENT_WINDOW_DAYS", 90),
("ASR_PROVIDER", "qwen"),
("YOUTUBE_ASR_ENABLED", True),
```

2. Add to `_DEFAULTS`:
```python
"SYNC_ASR_ENABLED": True,
"SYNC_RECENT_WINDOW_DAYS": 90,
"ASR_PROVIDER": "qwen",
"YOUTUBE_ASR_ENABLED": True,
```

Also add `YOUTUBE_ASR_ENABLED` to sensitive config masking in `get_all_config()`.

Run: `pytest backend/tests/ -k "config" -v`

---

- [ ] **Step 7: Commit**

```bash
git add backend/tools/asr_service.py backend/parsers/media_parser_protocol.py backend/parsers/media_router.py backend/config.py backend/tests/test_asr_service.py backend/tests/test_media_parser_protocol.py backend/tests/test_media_router.py
git commit -m "feat: add ASRService, MediaParser protocol, and MediaRouter"
```

---

## Chunk 2: Platform Parsers — YouTube + Refactored Bilibili

### Files

- Create: `backend/parsers/youtube_parser.py`
- Modify: `backend/parsers/bilibili_parser.py` (refactor to implement MediaParser)
- Modify: `backend/parsers/audio_parser.py` (implement MediaParser)
- Test: `backend/tests/test_youtube_parser.py`, `backend/tests/test_bilibili_parser_refactor.py`

---

- [ ] **Step 1: Write failing test for YouTubeMediaParser**

```python
# backend/tests/test_youtube_parser.py
import pytest
from unittest.mock import patch, MagicMock
from parsers.youtube_parser import YouTubeMediaParser
from parsers.media_parser_protocol import ParsedMediaContent

class TestYouTubeMediaParser:
    def test_supports_youtube_urls(self):
        parser = YouTubeMediaParser()
        assert parser.supports("https://www.youtube.com/watch?v=abc") is True
        assert parser.supports("https://youtu.be/abc") is True
        assert parser.supports("https://bilibili.com/video/BV123") is False

    def test_parse_with_subtitle(self):
        """字幕优先策略"""
        parser = YouTubeMediaParser()
        with patch.object(parser, '_get_subtitle', return_value="这是字幕文本"):
            result = parser.parse("https://www.youtube.com/watch?v=test", "video")
            assert result is not None
            assert result.transcript == "这是字幕文本"
            assert result.source == "subtitle"

    def test_parse_falls_back_to_asr(self):
        """无字幕时回退到 ASR"""
        parser = YouTubeMediaParser()
        with patch.object(parser, '_get_subtitle', return_value=None):
            with patch.object(parser, 'get_audio_url', return_value="http://audio.url"):
                with patch("tools.asr_service.ASRService.transcribe", return_value="ASR转录文本"):
                    result = parser.parse("https://www.youtube.com/watch?v=test", "video")
                    assert result is not None
                    assert result.source == "asr"
```

Run: `pytest backend/tests/test_youtube_parser.py -v`
Expected: FAIL — module doesn't exist

---

- [ ] **Step 2: Implement `YouTubeMediaParser`**

```python
# backend/parsers/youtube_parser.py
"""
YouTube 视频解析器 - 字幕 + ASR
实现 MediaParser Protocol
"""
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

import requests

# yt-dlp at module level (following codebase convention)
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

from .media_parser_protocol import MediaParser, ParsedMediaContent

logger = logging.getLogger(__name__)


class YouTubeMediaParser:
    """YouTube 视频解析器 - 字幕优先，ASR回退"""

    def supports(self, url: str) -> bool:
        return "youtube.com" in url or "youtu.be" in url

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        """
        解析YouTube视频
        策略: 字幕 → ASR → description
        """
        video_id = self._extract_video_id(url)
        if not video_id:
            return None

        # 1. 尝试字幕
        subtitle_text = self._get_subtitle(video_id)
        if subtitle_text and len(subtitle_text) >= 50:
            return ParsedMediaContent(
                transcript=subtitle_text,
                source="subtitle",
                media_type=media_type,
                language="zh"
            )

        # 2. ASR
        if media_type == "video":
            try:
                audio_url = self.get_audio_url(url, credentials)
                if audio_url:
                    from tools.asr_service import ASRService
                    asr_svc = ASRService()
                    transcript = asr_svc.transcribe_url(audio_url, f"{video_id}.m4a")
                    if transcript and len(transcript) >= 50:
                        return ParsedMediaContent(
                            transcript=transcript,
                            source="asr",
                            media_type=media_type,
                            language=None
                        )
            except Exception as e:
                logger.warning(f"[YouTubeParser] ASR failed for {video_id}: {e}")

        # 3. Fallback: description
        description = self._get_description(video_id)
        if description:
            return ParsedMediaContent(
                transcript=description,
                source="description",
                media_type=media_type,
                language=None
            )

        return None

    def get_audio_url(self, url: str, credentials: dict = None) -> Optional[str]:
        """获取音频流URL (用于ASR)"""
        if yt_dlp is None:
            logger.warning("[YouTubeParser] yt-dlp not installed, cannot get audio URL")
            return None

        video_id = self._extract_video_id(url)
        if not video_id:
            return None

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://youtu.be/{video_id}", download=False)
                if info and 'url' in info:
                    return info['url']
                # Try to get from formats
                for fmt in info.get('formats', []):
                    if fmt.get('vcodec') == 'none' and fmt.get('acodec'):
                        return fmt.get('url')
        except Exception as e:
            logger.warning(f"[YouTubeParser] Failed to get audio URL: {e}")
        return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """从URL提取视频ID"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _get_subtitle(self, video_id: str) -> Optional[str]:
        """获取YouTube字幕"""
        subtitle_url = (
            f"https://youtube.com/api/timedtext?v={video_id}"
            "&asr_langs=zh-Hans,zh-Hant,en&fmt=json3"
        )
        try:
            resp = requests.get(subtitle_url, timeout=10,
                              headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                # Try auto-generated
                subtitle_url = (
                    f"https://youtube.com/api/timedtext?v={video_id}"
                    "&type=asr&lang=zh-Hans"
                )
                resp = requests.get(subtitle_url, timeout=10,
                                  headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json()
                texts = []
                for event in data.get("events", []):
                    segs = event.get("segs", [])
                    for seg in segs:
                        text = seg.get("utf8", "")
                        if text:
                            texts.append(text)
                if texts:
                    return " ".join(texts)
        except Exception as e:
            logger.debug(f"[YouTubeParser] Subtitle fetch failed: {e}")
        return None

    def _get_description(self, video_id: str) -> str:
        """获取视频描述作为fallback"""
        if yt_dlp is None:
            return ""
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(f"https://youtu.be/{video_id}", download=False)
                return info.get("description", "") or ""
        except Exception:
            return ""
```

Run: `pytest backend/tests/test_youtube_parser.py -v`

---

- [ ] **Step 3: Refactor `BilibiliParser` to implement `MediaParser`**

Modify `backend/parsers/bilibili_parser.py` to add `MediaParser` methods:

Add to `BilibiliParser` class:
```python
from .media_parser_protocol import MediaParser, ParsedMediaContent

class BilibiliParser:
    # ... existing code ...

    def supports(self, url: str) -> bool:
        return "bilibili.com" in url

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        """实现 MediaParser.parse()"""
        bvid = self._extract_bvid(url)
        if not bvid:
            return None

        # 如果传入了 credentials，覆盖实例的 cookie
        if credentials:
            if credentials.get('sessdata'):
                self.sessdata = credentials['sessdata']
            if credentials.get('bili_jct'):
                self.bili_jct = credentials['bili_jct']
            if credentials.get('dedeuserid'):
                self.dedeuserid = credentials['dedeuserid']

        # 获取 cid
        video_info = self.get_video_info(bvid)
        if not video_info:
            return None

        cid = video_info.get("cid", 0)

        # 使用字幕
        subtitle_text = self.get_subtitle(bvid, cid, video_info)
        if subtitle_text and len(subtitle_text) >= 50:
            return ParsedMediaContent(
                transcript=subtitle_text,
                source="subtitle",
                media_type=media_type,
                language="zh"
            )

        # ASR
        if media_type == "video":
            audio_url = self.get_audio_url(bvid, cid)
            if audio_url:
                try:
                    from tools.asr_service import ASRService
                    asr_svc = ASRService()
                    transcript = asr_svc.transcribe_url(audio_url, f"{bvid}.m4s")
                    if transcript and len(transcript) >= 50:
                        return ParsedMediaContent(
                            transcript=transcript,
                            source="asr",
                            media_type=media_type,
                            language=None
                        )
                except Exception as e:
                    logger.warning(f"[BilibiliParser] ASR failed: {e}")

        # description fallback
        description = video_info.get("desc", "")
        if description:
            return ParsedMediaContent(
                transcript=description,
                source="description",
                media_type=media_type,
                language=None
            )

        return None

    def get_audio_url(self, url: str, credentials: dict = None) -> Optional[str]:
        """
        实现 MediaParser.get_audio_url()
        注意：Bilibili 的音频 URL 需要 bvid+cid，所以这里只返回传入 URL 的 bvid 解析结果
        本方法在 MediaRouter 中不会被直接调用（MediaRouter 调用 parse()）
        """
        bvid = self._extract_bvid(url)
        if not bvid:
            return None
        video_info = self.get_video_info(bvid)
        if not video_info:
            return None
        cid = video_info.get("cid", 0)
        return self.get_audio_url(bvid, cid)

    def _extract_bvid(self, url: str) -> Optional[str]:
        """从URL提取BV号"""
        match = re.search(r'BV[a-zA-Z0-9]+', url)
        return match.group(0) if match else None
```

**关键变更**: 重构 `parse_video()` 使其调用新的 `parse()` 逻辑（保持向后兼容）。原来的 `parse_video()` 内部调用链保持不变，只在类上添加 `MediaParser` protocol 方法。

Run: `pytest backend/tests/test_bilibili_parser_refactor.py -v`

---

- [ ] **Step 4: Implement `AudioMediaParser`**

Modify `backend/parsers/audio_parser.py` to add `MediaParser` protocol:

```python
# Add to audio_parser.py
from .media_parser_protocol import MediaParser, ParsedMediaContent

class AudioMediaParser:
    """通用音频解析器 - 直接 ASR"""

    def supports(self, url: str) -> bool:
        # 支持常见音频URL
        audio_domains = ["douyinv", "v.douyin", "xigua", "music"]
        return any(domain in url for domain in audio_domains)

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        if media_type != "audio":
            return None
        try:
            from tools.asr_service import ASRService
            asr_svc = ASRService()
            transcript = asr_svc.transcribe_url(url, "audio.mp3")
            if transcript:
                return ParsedMediaContent(
                    transcript=transcript,
                    source="asr",
                    media_type=media_type,
                    language=None
                )
        except Exception as e:
            logger.warning(f"[AudioMediaParser] ASR failed: {e}")
        return None

    def get_audio_url(self, url: str, credentials: dict = None) -> Optional[str]:
        return url  # Already an audio URL
```

Run: `pytest backend/tests/test_audio_parser.py -v`

---

- [ ] **Step 5: Commit**

```bash
git add backend/parsers/youtube_parser.py backend/parsers/bilibili_parser.py backend/parsers/audio_parser.py backend/tests/test_youtube_parser.py backend/tests/test_bilibili_parser_refactor.py
git commit -m "feat: add YouTubeMediaParser and refactor BilibiliParser to MediaParser protocol"
```

---

## Chunk 3: Collector Agent Integration

### Files

- Modify: `backend/agents/collector_agent.py`
- Test: `backend/tests/test_collector_agent_integration.py`

---

- [ ] **Step 1: Write failing integration test**

```python
# backend/tests/test_collector_agent_integration.py
import pytest
from unittest.mock import patch, MagicMock
from agents.collector_agent import CollectorAgent
from memory.memory_schema import RawContent

class TestCollectorAgentMediaRouting:
    def test_media_router_is_called_for_video(self):
        """collector_agent 使用 MediaRouter 路由视频内容"""
        agent = CollectorAgent()
        # ... mock platform connector returning video content
        # ... verify MediaRouter.route() is called
```

Run: `pytest backend/tests/test_collector_agent_integration.py -v`
Expected: FAIL

---

- [ ] **Step 2: Refactor `collector_agent._parse_content()` to use `MediaRouter`**

In `backend/agents/collector_agent.py`:

```python
# At top of file, init global router (lazy)
_media_router = None

def _get_media_router():
    global _media_router
    if _media_router is None:
        from parsers.media_router import MediaRouter
        from parsers.bilibili_parser import BilibiliParser
        from parsers.youtube_parser import YouTubeMediaParser
        from parsers.audio_parser import AudioMediaParser

        router = MediaRouter()
        router.register(BilibiliParser())
        router.register(YouTubeMediaParser())
        router.register(AudioMediaParser())
        _media_router = router
    return _media_router


def _parse_content(content: RawContent, llm_func=None, user_id: str = "") -> RawContent:
    """
    解析 RawContent 内容
    使用 MediaRouter 统一路由音视频
    """
    media_type = content.media_type

    # 文本/网页：提取主体正文（保持原有逻辑）
    if media_type == "text":
        if content.url and (not content.body or len(content.body) < 200):
            try:
                from parsers.text_parser import parse_webpage
                parsed = parse_webpage(content.url, fallback_content=content.body)
                if parsed and len(parsed) > len(content.body or ""):
                    content.body = parsed
            except Exception as e:
                logger.debug(f"[Collector] 网页解析失败: {e}")
        return content

    # Repo: Markdown解析
    if media_type == "repo":
        if content.body:
            try:
                from parsers.text_parser import parse_markdown
                parsed = parse_markdown(content.body)
                if parsed:
                    content.body = parsed[:5000]
            except Exception as e:
                logger.debug(f"[Collector] Markdown解析失败: {e}")
        return content

    # PDF
    if media_type == "pdf":
        if content.url:
            try:
                from parsers.pdf_parser import parse_pdf
                result = parse_pdf(content.url)
                if result.get("text"):
                    content.body = result["text"][:5000]
                    if result.get("title") and not content.title:
                        content.title = result["title"]
            except Exception as e:
                logger.debug(f"[Collector] PDF解析失败: {e}")
        return content

    # 图片（Qwen2-VL）
    if media_type == "image":
        if content.thumbnail_url and not content.body:
            try:
                from parsers.vision_parser import describe_image
                desc = describe_image(content.thumbnail_url)
                if desc:
                    content.body = desc
            except Exception as e:
                logger.debug(f"[Collector] 图像理解失败: {e}")
        return content

    # 音视频：使用 MediaRouter (subtitle → ASR)
    if media_type in ("video", "audio"):
        try:
            router = _get_media_router()
            result = router.route(content, llm_func=llm_func)
            if result and result.transcript:
                content.body = result.transcript[:5000]  # 截断防止过大
                logger.info(f"[Collector] MediaRouter 解析成功: platform={content.platform}, "
                           f"source={result.source}, len={len(result.transcript)}")
        except Exception as e:
            logger.warning(f"[Collector] MediaRouter 解析失败: {e}")

    return content
```

**删除原来的 `elif media_type == "video"` 分支** 和 `elif media_type == "audio"` 分支及所有平台特殊处理代码（bilibili/youtube/video_parser/等），替换为统一的 `MediaRouter` 调用。

Run: `pytest backend/tests/test_collector_agent_integration.py -v`

---

- [ ] **Step 3: Commit**

```bash
git add backend/agents/collector_agent.py
git commit -m "refactor: integrate MediaRouter into collector_agent, remove per-platform branching"
```

---

## Chunk 4: MCP Tools + Settings UI

### Files

- Modify: `backend/tools/mcp_tools.py` (add ASR config getters/setters)
- Modify: `frontend/src/pages/Settings.tsx` (add ASR config UI)
- Modify: `backend/tools/config_manager.py` (if exists) or `backend/routers/admin.py`
- Test: `backend/tests/test_mcp_asr_config.py`

---

- [ ] **Step 1: Add ASR config MCP tools**

In `backend/tools/mcp_tools.py`, add:

```python
@mcp_tool
def get_asr_config() -> dict:
    """获取 ASR 配置"""
    import config
    return {
        "sync_asr_enabled": getattr(config, 'SYNC_ASR_ENABLED', True),
        "sync_recent_window_days": getattr(config, 'SYNC_RECENT_WINDOW_DAYS', 90),
        "asr_provider": getattr(config, 'ASR_PROVIDER', 'qwen'),
        "bilibili_asr_enabled": getattr(config, 'BILIBILI_ASR_ENABLED', True),
        "youtube_asr_enabled": getattr(config, 'YOUTUBE_ASR_ENABLED', True),
    }

@mcp_tool
def update_asr_config(
    sync_asr_enabled: bool = None,
    sync_recent_window_days: int = None,
    asr_provider: str = None,
    bilibili_asr_enabled: bool = None,
    youtube_asr_enabled: bool = None,
) -> dict:
    """更新 ASR 配置"""
    import config
    updates = {}
    if sync_asr_enabled is not None:
        updates['SYNC_ASR_ENABLED'] = sync_asr_enabled
    if sync_recent_window_days is not None:
        updates['SYNC_RECENT_WINDOW_DAYS'] = sync_recent_window_days
    if asr_provider is not None:
        updates['ASR_PROVIDER'] = asr_provider
    if bilibili_asr_enabled is not None:
        updates['BILIBILI_ASR_ENABLED'] = bilibili_asr_enabled
    if youtube_asr_enabled is not None:
        updates['YOUTUBE_ASR_ENABLED'] = youtube_asr_enabled

    config.update_runtime(updates)
    return {"status": "ok", "updated": list(updates.keys())}
```

---

- [ ] **Step 2: Update Settings frontend**

In `frontend/src/pages/Settings.tsx`, add ASR config section:

```tsx
// Add state
const [asrConfig, setAsrConfig] = useState({
  sync_asr_enabled: true,
  sync_recent_window_days: 90,
  asr_provider: 'qwen',
  bilibili_asr_enabled: true,
  youtube_asr_enabled: true,
});

// Add fetch on mount
useEffect(() => {
  apiClient.get('/config').then(/* parse and set */);
}, []);

// Add UI section
<section>
  <h3>音视频转录设置</h3>
  <label>
    <input type="checkbox"
      checked={asrConfig.sync_asr_enabled}
      onChange={e => updateAsrConfig({ sync_asr_enabled: e.target.checked })}
    />
    同步时自动转录音视频
  </label>
  <label>
    转录范围（天数）:
    <input type="number" value={asrConfig.sync_recent_window_days}
      onChange={e => updateAsrConfig({ sync_recent_window_days: Number(e.target.value) })}
    />
  </label>
  <fieldset>
    <legend>ASR Provider</legend>
    <label><input type="radio" name="asr_provider" value="qwen"
      checked={asrConfig.asr_provider === 'qwen'}
      onChange={e => updateAsrConfig({ asr_provider: 'qwen' })}
    /> Qwen (vLLM)</label>
    <label><input type="radio" name="asr_provider" value="whisper"
      checked={asrConfig.asr_provider === 'whisper'}
      onChange={e => updateAsrConfig({ asr_provider: 'whisper' })}
    /> Whisper (本地)</label>
  </fieldset>
  <label>
    <input type="checkbox"
      checked={asrConfig.bilibili_asr_enabled}
      onChange={e => updateAsrConfig({ bilibili_asr_enabled: e.target.checked })}
    />
    Bilibili
  </label>
  <label>
    <input type="checkbox"
      checked={asrConfig.youtube_asr_enabled}
      onChange={e => updateAsrConfig({ youtube_asr_enabled: e.target.checked })}
    />
    YouTube
  </label>
</section>
```

Run: `cd frontend && npm run build` to verify no TS errors

---

- [ ] **Step 3: Commit**

```bash
git add backend/tools/mcp_tools.py frontend/src/pages/Settings.tsx
git commit -m "feat: add ASR config MCP tools and Settings UI"
```

---

## Verification

1. **手动测试流程**:
   ```bash
   # 1. 启动后端
   cd backend && python main.py serve

   # 2. 触发Bilibili同步（有字幕视频）
   python main.py sync --platform bilibili

   # 3. 触发YouTube同步（如果有cookie）
   python main.py sync --platform youtube

   # 4. 验证转录文本被存储
   python main.py query "视频里说了什么"

   # 5. 触发GitHub同步（纯文本，应该不触发ASR）
   python main.py sync --platform github
   ```

2. **确认不触发ASR的平台**:
   - GitHub → 直接提取 README，不走 MediaRouter
   - 已有字幕的 Bilibili → 字幕优先，不走 ASR

3. **Settings UI**:
   - 打开 Settings 页面 → 确认"音视频转录设置"区块显示
   - 修改配置 → POST /config → 验证 runtime 更新
