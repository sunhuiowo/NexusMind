"""
parsers/video_parser.py
视频解析器 - 分层摘要策略
Whisper ASR + Qwen2-VL 关键帧 + 分段摘要 + 全局摘要
节省约 90% Embedding 计算成本
"""

import os
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from parsers.audio_parser import transcribe_audio, format_transcript_with_timestamps
from parsers.vision_parser import describe_video_frame

logger = logging.getLogger(__name__)


@dataclass
class VideoSegment:
    """视频分段"""
    start: float      # 秒
    end: float
    text: str         # Whisper 转录文本
    summary: str = "" # LLM 生成分段摘要
    keyframe_desc: str = ""  # Qwen2-VL 关键帧描述


@dataclass
class VideoParseResult:
    """视频解析结果"""
    full_transcript: str           # 带时间戳全文转录
    segments: List[VideoSegment]   # 分段列表
    keyframe_descriptions: List[Dict] = field(default_factory=list)  # [{time, desc}]
    global_summary: str = ""       # 全局摘要（100字以内，用于 Embedding）
    language: str = ""
    duration_sec: float = 0.0


def _extract_keyframes(
    video_path: str,
    duration_sec: float,
    tmp_dir: str,
) -> List[Tuple[float, str]]:
    """
    提取视频关键帧
    长视频（>5分钟）：每分钟1帧；短视频：每30秒1帧
    返回 [(timestamp_sec, frame_path), ...]
    """
    try:
        import cv2
    except ImportError:
        logger.warning("[VideoParser] opencv-python 未安装，跳过关键帧提取")
        return []

    is_short = duration_sec < config.VIDEO_SHORT_THRESHOLD_SEC
    interval = (
        config.VIDEO_KEYFRAME_INTERVAL_SHORT if is_short
        else config.VIDEO_KEYFRAME_INTERVAL_LONG
    )

    frames = []
    cap = cv2.VideoCapture(video_path)

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        timestamps = list(range(0, int(duration_sec), interval))
        if not timestamps:
            timestamps = [0]

        for ts in timestamps:
            frame_num = int(ts * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                continue

            frame_path = os.path.join(tmp_dir, f"frame_{ts:05d}.jpg")
            cv2.imwrite(frame_path, frame)
            frames.append((float(ts), frame_path))

    finally:
        cap.release()

    logger.info(f"[VideoParser] 提取 {len(frames)} 个关键帧")
    return frames


def _segment_transcript(
    segments: List[Dict],
    segment_duration_sec: float = 120,  # 每段约2分钟
) -> List[VideoSegment]:
    """将 Whisper 分段按时间窗口合并为更大的段落"""
    if not segments:
        return []

    video_segments = []
    current_start = 0.0
    current_texts = []
    current_end = 0.0

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        seg_text = seg.get("text", "").strip()

        if not seg_text:
            continue

        # 新段落判断
        if current_texts and (seg_start - current_start) >= segment_duration_sec:
            video_segments.append(VideoSegment(
                start=current_start,
                end=current_end,
                text=" ".join(current_texts),
            ))
            current_start = seg_start
            current_texts = []

        current_texts.append(seg_text)
        current_end = seg_end

    # 最后一段
    if current_texts:
        video_segments.append(VideoSegment(
            start=current_start,
            end=current_end,
            text=" ".join(current_texts),
        ))

    return video_segments


def _generate_segment_summary(text: str, llm_func=None) -> str:
    """用 LLM 生成分段摘要"""
    if not text:
        return ""
    if llm_func:
        try:
            return llm_func(
                f"请用2句话总结以下视频片段内容：\n\n{text[:2000]}"
            )
        except Exception:
            pass
    # 降级：截取前100字
    return text[:100] + "..." if len(text) > 100 else text


def _generate_global_summary(
    segments: List[VideoSegment],
    keyframe_descs: List[Dict],
    llm_func=None,
) -> str:
    """生成全局视频摘要（100字以内）"""
    segment_summaries = [s.summary or s.text[:100] for s in segments if s.text]
    combined = "\n".join(segment_summaries[:10])  # 取前10段

    if keyframe_descs:
        visual_info = "；".join([d.get("desc", "")[:50] for d in keyframe_descs[:3]])
        combined = f"视觉内容：{visual_info}\n\n语音内容：{combined}"

    if llm_func:
        try:
            return llm_func(
                f"请用100字以内总结以下视频的核心内容，突出主题和关键信息：\n\n{combined[:3000]}"
            )
        except Exception:
            pass

    # 降级
    all_text = " ".join(segment_summaries)
    return all_text[:200] + "..." if len(all_text) > 200 else all_text


def parse_video(
    video_source: str,  # 本地路径 或 URL
    llm_func=None,      # LLM 调用函数，signature: (prompt: str) -> str
    language: str = None,
) -> VideoParseResult:
    """
    视频分层摘要解析
    1. Whisper 全文转录（带时间戳）
    2. 按语义边界分段
    3. Qwen2-VL 关键帧描述
    4. LLM 生成分段摘要和全局
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Step 1: 处理视频文件
        if video_source.startswith("http://") or video_source.startswith("https://"):
            local_path = _download_video(video_source, tmp_dir)
            if not local_path:
                return VideoParseResult(
                    full_transcript="",
                    segments=[],
                    global_summary="视频内容无法获取",
                )
        else:
            local_path = video_source

        # Step 2: 获取视频时长
        duration_sec = _get_duration(local_path)

        # Step 3: Whisper ASR
        logger.info(f"[VideoParser] 开始 ASR 转录，时长: {duration_sec:.0f}s")
        asr_result = transcribe_audio(local_path, language=language, return_timestamps=True)
        full_transcript = format_transcript_with_timestamps(asr_result.get("segments", []))

        # Step 4: 分段
        raw_segments = _segment_transcript(asr_result.get("segments", []))

        # Step 5: Qwen2-VL 关键帧（在临时目录内）
        keyframe_descs = []
        try:
            frames = _extract_keyframes(local_path, duration_sec, tmp_dir)
            for ts, frame_path in frames:
                desc = describe_video_frame(frame_path, ts)
                if desc:
                    keyframe_descs.append({"time": ts, "desc": desc})
        except Exception as e:
            logger.warning(f"[VideoParser] 关键帧提取失败（跳过）: {e}")

        # Step 6: 生成分段摘要
        for seg in raw_segments:
            seg.summary = _generate_segment_summary(seg.text, llm_func)

        # Step 7: 全局摘要
        global_summary = _generate_global_summary(raw_segments, keyframe_descs, llm_func)

        return VideoParseResult(
            full_transcript=full_transcript,
            segments=raw_segments,
            keyframe_descriptions=keyframe_descs,
            global_summary=global_summary,
            language=asr_result.get("language", ""),
            duration_sec=duration_sec,
        )


def _get_duration(video_path: str) -> float:
    """获取视频时长（秒）"""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return total_frames / fps if fps > 0 else 0
    except Exception:
        return 0.0


def _download_video(url: str, tmp_dir: str) -> Optional[str]:
    """下载视频（支持直链和 yt-dlp）"""
    # 尝试直接下载
    try:
        import requests
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        tmp_path = os.path.join(tmp_dir, "video.mp4")
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return tmp_path
    except Exception:
        pass

    # 尝试 yt-dlp（YouTube 等）
    try:
        import yt_dlp
        ydl_opts = {
            "outtmpl": os.path.join(tmp_dir, "video.%(ext)s"),
            "format": "bestaudio/best",
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get("ext", "mp4")
            return os.path.join(tmp_dir, f"video.{ext}")
    except Exception as e:
        logger.error(f"[VideoParser] 视频下载失败: {e}")
        return None
