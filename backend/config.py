"""
config.py
全局配置 — 支持运行时热更新
优先级：环境变量 > runtime_overrides（POST /config 写入）> 默认值
"""

import os
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUTH_DIR = DATA_DIR / "auth"
VECTOR_DIR = DATA_DIR / "vectors"
RUNTIME_CONFIG_PATH = DATA_DIR / "runtime_config.json"
USERS_DB_PATH = DATA_DIR / "users.db"

for _d in [DATA_DIR, AUTH_DIR, VECTOR_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# 运行时覆盖（由 POST /config 写入）
_runtime_overrides: dict = {}
if RUNTIME_CONFIG_PATH.exists():
    try:
        _runtime_overrides = json.loads(RUNTIME_CONFIG_PATH.read_text())
    except Exception:
        _runtime_overrides = {}


def _get(key: str, default=None):
    if key in _runtime_overrides:
        v = _runtime_overrides[key]
    else:
        v = os.getenv(key)
    if v is None:
        return default
    # Type coerce based on default type
    if isinstance(default, bool):
        return str(v).lower() in ("true", "1", "yes")
    if isinstance(default, int):
        try: return int(v)
        except: return default
    if isinstance(default, float):
        try: return float(v)
        except: return default
    if isinstance(default, list):
        return v.split(",") if isinstance(v, str) else v
    return v


def update_runtime(updates: dict) -> None:
    global _runtime_overrides
    _runtime_overrides.update(updates)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(_runtime_overrides, ensure_ascii=False, indent=2))


def get_all_config() -> dict:
    def mask(k):
        v = _get(k, "")
        if not v: return ""
        s = str(v)
        return s[:4] + "****" + s[-4:] if len(s) > 8 else "****"

    sensitive = {"LLM_API_KEY", "ANTHROPIC_API_KEY", "YOUTUBE_CLIENT_SECRET",
                 "TWITTER_CLIENT_SECRET", "GITHUB_CLIENT_SECRET", "GITHUB_PAT",
                 "BILIBILI_CLIENT_SECRET", "DOUYIN_CLIENT_SECRET",
                 "POCKET_CONSUMER_KEY", "WECHAT_API_KEY",
                 "TOKEN_MASTER_PASSWORD", "TOKEN_ENCRYPT_KEY", "API_SECRET_KEY"}

    result = {}
    for k, default in [
        ("LLM_PROVIDER","auto"), ("LLM_MODEL","gpt-4o-mini"), ("LLM_BASE_URL",""),
        ("LLM_API_KEY",""), ("ANTHROPIC_API_KEY",""), ("AZURE_OPENAI_API_VERSION","2024-02-01"),
        ("EMBEDDING_PROVIDER",""), ("EMBEDDING_MODEL","text-embedding-3-small"), ("EMBEDDING_DIM",1536), ("EMBEDDING_BASE_URL",""),
        ("PLATFORMS_ENABLED",""), ("SYNC_INTERVAL_HOURS",6), ("TOP_K_RESULTS",5),
        ("IMPORTANCE_DECAY_RATE",0.99), ("IMPORTANCE_DECAY_DAYS_THRESHOLD",30),
        ("WHISPER_MODEL_SIZE","base"), ("WHISPER_DEVICE","cpu"),
        ("TTS_ENABLED",False), ("TTS_LANGUAGE","zh-cn"),
        ("YOUTUBE_CLIENT_ID",""), ("YOUTUBE_CLIENT_SECRET",""),
        ("TWITTER_CLIENT_ID",""), ("TWITTER_CLIENT_SECRET",""),
        ("GITHUB_CLIENT_ID",""), ("GITHUB_PAT",""),
        ("BILIBILI_CLIENT_ID",""), ("DOUYIN_CLIENT_ID",""),
        ("POCKET_CONSUMER_KEY",""), ("WECHAT_API_KEY",""),
    ]:
        result[k] = mask(k) if k in sensitive else _get(k, default)
    return result


# ── 模块属性动态访问（import config; config.XXX 语法）────────────────────────
import sys as _sys

_DEFAULTS = {
    "LLM_PROVIDER": "auto", "LLM_MODEL": "gpt-4o-mini",
    "LLM_API_KEY": "", "LLM_BASE_URL": "", "ANTHROPIC_API_KEY": "",
    "AZURE_OPENAI_API_VERSION": "2024-02-01",
    "EMBEDDING_PROVIDER": "", "EMBEDDING_MODEL": "text-embedding-3-small", "EMBEDDING_DIM": 1536, "EMBEDDING_BASE_URL": "",
    "PLATFORMS_ENABLED": "youtube,twitter,github,pocket,bilibili,wechat,douyin,xiaohongshu",
    "YOUTUBE_CLIENT_ID": "", "YOUTUBE_CLIENT_SECRET": "",
    "TWITTER_CLIENT_ID": "", "TWITTER_CLIENT_SECRET": "",
    "GITHUB_CLIENT_ID": "", "GITHUB_CLIENT_SECRET": "", "GITHUB_PAT": "",
    "BILIBILI_CLIENT_ID": "", "BILIBILI_CLIENT_SECRET": "",
    "BILIBILI_ASR_ENABLED": False,  # B站视频ASR转录默认禁用，避免内存问题
    "DOUYIN_CLIENT_ID": "", "DOUYIN_CLIENT_SECRET": "",
    "POCKET_CONSUMER_KEY": "", "WECHAT_API_KEY": "", "XIAOHONGSHU_COOKIE": "",
    "TOKEN_MASTER_PASSWORD": "", "TOKEN_ENCRYPT_KEY": "",
    "TOP_K_RESULTS": 5, "MIN_IMPORTANCE_THRESHOLD": 0.0,
    "SYNC_INTERVAL_HOURS": 6, "SYNC_BATCH_SIZE": 100,
    "IMPORTANCE_DECAY_RATE": 0.99, "IMPORTANCE_DECAY_DAYS_THRESHOLD": 30, "IMPORTANCE_QUERY_BOOST": 0.05,
    "WHISPER_MODEL_SIZE": "base", "WHISPER_DEVICE": "cpu",
    "QWEN_VL_MODEL": "Qwen/Qwen2-VL-7B-Instruct", "QWEN_VL_DEVICE": "cpu",
    "VIDEO_KEYFRAME_INTERVAL_LONG": 60, "VIDEO_KEYFRAME_INTERVAL_SHORT": 30, "VIDEO_SHORT_THRESHOLD_SEC": 300,
    "TTS_ENABLED": False, "TTS_LANGUAGE": "zh-cn", "TTS_SPEAKER_WAV": "",
    "API_HOST": "0.0.0.0", "API_PORT": 8000, "API_SECRET_KEY": "change-me-in-production",
    "OAUTH_CALLBACK_BASE": "http://localhost:8000", "OAUTH_CALLBACK_PATH": "/auth/callback",
    "COOKIE_EXPIRE_WARN_DAYS": 7, "TOKEN_REFRESH_BEFORE_MINUTES": 5,
}


class _DynModule(_sys.modules[__name__].__class__):
    def __getattr__(self, name: str):
        if name in _DEFAULTS:
            return _get(name, _DEFAULTS[name])
        if name == "FAISS_INDEX_PATH":
            return _get(name, str(VECTOR_DIR / "faiss_index"))
        if name == "METADATA_DB_PATH":
            return _get(name, str(DATA_DIR / "memories.db"))
        raise AttributeError(f"module 'config' has no attribute '{name}'")


_sys.modules[__name__].__class__ = _DynModule
