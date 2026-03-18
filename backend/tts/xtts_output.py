"""
tts/xtts_output.py
XTTS 语音播报
将 QueryResult 综合总结转为语音输出
"""

import logging
import io
import os
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

_tts_model = None


def _load_model():
    """懒加载 XTTS 模型"""
    global _tts_model
    if _tts_model is not None:
        return _tts_model

    try:
        from TTS.api import TTS
        logger.info("[TTS] 加载 XTTS 模型...")
        _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
        logger.info("[TTS] XTTS 模型加载完成")
        return _tts_model
    except ImportError:
        logger.error("[TTS] TTS 未安装，请运行: pip install TTS")
        return None
    except Exception as e:
        logger.error(f"[TTS] 模型加载失败: {e}")
        return None


def speak(text: str, output_path: str = None, language: str = None) -> Optional[str]:
    """
    将文本转为语音
    output_path: 保存路径（None 则自动生成）
    language: 语言代码（默认从 config 读取）
    返回音频文件路径
    """
    if not config.TTS_ENABLED:
        logger.debug("[TTS] TTS 未启用，跳过")
        return None

    if not text or not text.strip():
        return None

    model = _load_model()
    if not model:
        return None

    language = language or config.TTS_LANGUAGE or "zh-cn"

    if output_path is None:
        import tempfile
        output_path = os.path.join(tempfile.mkdtemp(), "tts_output.wav")

    try:
        kwargs = {
            "text": text,
            "language": language,
            "file_path": output_path,
        }

        # 如果有参考音色文件
        if config.TTS_SPEAKER_WAV and os.path.exists(config.TTS_SPEAKER_WAV):
            kwargs["speaker_wav"] = config.TTS_SPEAKER_WAV

        model.tts_to_file(**kwargs)
        logger.info(f"[TTS] 语音生成完成: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"[TTS] 语音合成失败: {e}")
        return None


def speak_and_play(text: str, language: str = None) -> None:
    """
    生成语音并立即播放（本地环境）
    """
    audio_path = speak(text, language=language)
    if not audio_path:
        return

    try:
        # 尝试多种播放器
        import subprocess
        for player in ["afplay", "aplay", "mpg123", "ffplay"]:
            try:
                subprocess.run([player, audio_path], check=True, capture_output=True)
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    except Exception as e:
        logger.warning(f"[TTS] 播放失败: {e}")


def speak_query_result(result, language: str = None) -> Optional[str]:
    """
    将 QueryResult 转为语音（播报综合总结部分）
    """
    from memory.memory_schema import QueryResult

    if not isinstance(result, QueryResult):
        return None

    # 播报文本：总结 + 命中数
    speak_text = f"找到 {result.total_found} 条相关收藏。"
    if result.overall_summary:
        speak_text += result.overall_summary

    return speak(speak_text, language=language)
