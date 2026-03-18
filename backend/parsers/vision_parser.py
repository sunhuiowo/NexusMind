"""
parsers/vision_parser.py
视觉理解解析器 - Qwen2-VL 图像内容理解
支持单图和图组，支持视频关键帧
"""

import os
import logging
import base64
import tempfile
from pathlib import Path
from typing import List, Optional, Union

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# 全局模型缓存
_qwen_model = None
_qwen_processor = None


def _load_model():
    """懒加载 Qwen2-VL 模型"""
    global _qwen_model, _qwen_processor
    if _qwen_model is not None:
        return _qwen_model, _qwen_processor

    try:
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        import torch

        logger.info(f"[VisionParser] 加载 Qwen2-VL 模型: {config.QWEN_VL_MODEL}")
        _qwen_processor = AutoProcessor.from_pretrained(
            config.QWEN_VL_MODEL,
            trust_remote_code=True,
        )
        _qwen_model = Qwen2VLForConditionalGeneration.from_pretrained(
            config.QWEN_VL_MODEL,
            trust_remote_code=True,
            torch_dtype=torch.float16 if config.QWEN_VL_DEVICE != "cpu" else torch.float32,
        ).to(config.QWEN_VL_DEVICE)
        _qwen_model.eval()
        logger.info("[VisionParser] Qwen2-VL 模型加载完成")
        return _qwen_model, _qwen_processor

    except ImportError:
        logger.error("[VisionParser] transformers 未安装，请运行: pip install transformers")
        return None, None
    except Exception as e:
        logger.error(f"[VisionParser] Qwen2-VL 加载失败: {e}")
        return None, None


def _image_to_base64(image_path: str) -> str:
    """图片文件转 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _download_image(url: str, tmp_dir: str) -> Optional[str]:
    """下载图片到临时目录"""
    try:
        import requests
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0"
        })
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        elif "webp" in content_type:
            ext = ".webp"

        tmp_path = os.path.join(tmp_dir, f"image{ext}")
        with open(tmp_path, "wb") as f:
            f.write(resp.content)
        return tmp_path
    except Exception as e:
        logger.warning(f"[VisionParser] 图片下载失败 {url}: {e}")
        return None


def describe_image(
    image_source: str,  # 本地路径 或 URL
    prompt: str = "请描述这张图片的主要内容，包括文字信息、视觉元素和整体主题。",
) -> str:
    """
    使用 Qwen2-VL 描述单张图片
    返回图片内容描述文本
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        if image_source.startswith("http://") or image_source.startswith("https://"):
            local_path = _download_image(image_source, tmp_dir)
            if not local_path:
                return ""
        else:
            local_path = image_source

        return _run_qwen_vl(local_path, prompt)


def describe_image_group(
    image_sources: List[str],
    prompt: str = "请描述这组图片的整体内容和主题。",
) -> str:
    """
    描述图组（如小红书笔记的多张图片）
    分别描述每张，再汇总
    """
    if not image_sources:
        return ""

    descriptions = []
    for i, src in enumerate(image_sources[:6]):  # 最多处理 6 张
        desc = describe_image(
            src,
            prompt=f"这是第{i+1}张图，请简洁描述其内容。",
        )
        if desc:
            descriptions.append(f"图{i+1}：{desc}")

    if not descriptions:
        return ""

    # 汇总
    if len(descriptions) == 1:
        return descriptions[0]

    combined = "\n".join(descriptions)
    return _run_qwen_vl_text(
        combined,
        "以上是一组图片的描述，请提炼整体主题和核心信息，100字以内："
    ) or combined


def describe_video_frame(
    frame_path: str,
    timestamp_sec: float = 0,
) -> str:
    """描述视频关键帧"""
    prompt = f"视频第 {int(timestamp_sec // 60):02d}:{int(timestamp_sec % 60):02d} 处的画面内容："
    return _run_qwen_vl(frame_path, prompt)


def _run_qwen_vl(image_path: str, prompt: str) -> str:
    """执行 Qwen2-VL 图像理解推理"""
    model, processor = _load_model()
    if not model:
        return _fallback_description(image_path)

    try:
        from PIL import Image
        import torch

        image = Image.open(image_path).convert("RGB")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(
            text=[text],
            images=[image],
            return_tensors="pt",
            padding=True,
        ).to(config.QWEN_VL_DEVICE)

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
            )

        generated_ids = [
            out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)
        ]
        output_text = processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )[0]

        return output_text.strip()

    except Exception as e:
        logger.error(f"[VisionParser] 图像理解失败: {e}")
        return ""


def _run_qwen_vl_text(text_input: str, prompt: str) -> str:
    """文本摘要（无图片）"""
    model, processor = _load_model()
    if not model:
        return ""

    try:
        import torch

        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": f"{prompt}\n\n{text_input}"}],
            }
        ]

        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(text=[text], return_tensors="pt", padding=True).to(config.QWEN_VL_DEVICE)

        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=150, do_sample=False)

        generated_ids = [out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)]
        return processor.batch_decode(
            generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True
        )[0].strip()
    except Exception:
        return ""


def _fallback_description(image_path: str) -> str:
    """Qwen2-VL 不可用时的降级描述"""
    try:
        from PIL import Image
        img = Image.open(image_path)
        w, h = img.size
        mode = img.mode
        return f"图片（{w}×{h}，{mode} 模式）"
    except Exception:
        return "图片内容"
