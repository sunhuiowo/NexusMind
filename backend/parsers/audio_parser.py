"""
parsers/audio_parser.py
音频解析器 - Whisper ASR 本地推理封装
支持本地文件和 URL 下载
"""

import os
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Dict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


def _download_audio(url: str, tmp_dir: str) -> Optional[str]:
    """下载音频到临时目录，返回本地路径"""
    try:
        import requests
        resp = requests.get(url, stream=True, timeout=60, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PersonalAIMemory/1.0)"
        })
        resp.raise_for_status()

        # 从 Content-Type 或 URL 推断扩展名
        content_type = resp.headers.get("content-type", "")
        ext = ".mp3"
        if "mp4" in content_type or url.endswith(".mp4"):
            ext = ".mp4"
        elif "webm" in content_type or url.endswith(".webm"):
            ext = ".webm"
        elif "wav" in content_type:
            ext = ".wav"
        elif "ogg" in content_type:
            ext = ".ogg"

        tmp_path = os.path.join(tmp_dir, f"audio{ext}")
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return tmp_path
    except Exception as e:
        logger.error(f"[AudioParser] 下载音频失败 {url}: {e}")
        return None


def transcribe_audio(
    source: str,  # 本地文件路径 或 URL
    language: str = None,
    return_timestamps: bool = True,
) -> Dict:
    """
    使用 Whisper 转录音频
    返回: {text: str, segments: [{start, end, text}], language: str}
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 判断是 URL 还是本地文件
        if source.startswith("http://") or source.startswith("https://"):
            local_path = _download_audio(source, tmp_dir)
            if not local_path:
                return {"text": "", "segments": [], "language": ""}
        else:
            local_path = source
            if not os.path.exists(local_path):
                logger.error(f"[AudioParser] 文件不存在: {local_path}")
                return {"text": "", "segments": [], "language": ""}

        return _run_whisper(local_path, language, return_timestamps)


def _run_whisper(
    file_path: str,
    language: str = None,
    return_timestamps: bool = True,
) -> Dict:
    """执行 Whisper 推理"""
    try:
        import whisper
    except ImportError:
        logger.error("[AudioParser] whisper 未安装，请运行: pip install openai-whisper")
        return {"text": "", "segments": [], "language": ""}

    try:
        logger.info(f"[AudioParser] 加载 Whisper {config.WHISPER_MODEL_SIZE} 模型...")
        model = whisper.load_model(
            config.WHISPER_MODEL_SIZE,
            device=config.WHISPER_DEVICE,
        )

        transcribe_options = {
            "verbose": False,
            "task": "transcribe",
        }
        if language:
            transcribe_options["language"] = language

        logger.info(f"[AudioParser] 开始转录: {file_path}")
        result = model.transcribe(file_path, **transcribe_options)

        segments = []
        if return_timestamps:
            for seg in result.get("segments", []):
                segments.append({
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                })

        logger.info(f"[AudioParser] 转录完成，共 {len(result.get('text', ''))} 字符")
        return {
            "text": result.get("text", "").strip(),
            "segments": segments,
            "language": result.get("language", ""),
        }

    except Exception as e:
        logger.error(f"[AudioParser] Whisper 转录失败: {e}")
        return {"text": "", "segments": [], "language": ""}


def format_transcript_with_timestamps(segments: List[Dict]) -> str:
    """将分段转录结果格式化为带时间戳的文本"""
    if not segments:
        return ""

    lines = []
    for seg in segments:
        start = seg.get("start", 0)
        text = seg.get("text", "").strip()
        if text:
            mm = int(start // 60)
            ss = int(start % 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {text}")

    return "\n".join(lines)
