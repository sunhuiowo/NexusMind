"""
tools/llm.py
统一 LLM + Embedding 入口
支持：OpenAI / Anthropic / Azure OpenAI / Ollama / 任意 OpenAI 兼容端点
动态读取 config，运行时切换无需重启
"""

import logging
import hashlib
import struct
import re
from typing import List, Optional, Dict, Any
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLM Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LLMClient:
    """
    统一 LLM 调用封装
    provider 自动检测优先级：
      1. config.LLM_PROVIDER 显式指定
      2. 有 ANTHROPIC_API_KEY → anthropic
      3. 有 LLM_BASE_URL → openai_compatible (Ollama/本地)
      4. 有 LLM_API_KEY → openai
      5. fallback: 空响应 + 告警
    """

    def __init__(self):
        self._client = None
        self._provider: Optional[str] = None

    def _resolve(self):
        """解析当前生效的 provider + client（每次调用都重新读 config，支持热更新）"""
        import config as cfg

        provider = (cfg.LLM_PROVIDER or "").lower().strip()

        # 自动探测
        if not provider or provider == "auto":
            if cfg.ANTHROPIC_API_KEY:
                provider = "anthropic"
            elif cfg.LLM_BASE_URL:
                provider = "openai_compatible"
            elif cfg.LLM_API_KEY:
                provider = "openai"
            else:
                provider = "none"

        # Azure OpenAI
        if provider == "azure":
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=cfg.LLM_API_KEY,
                api_version=cfg.AZURE_OPENAI_API_VERSION or "2024-02-01",
                azure_endpoint=cfg.LLM_BASE_URL,
            )
            return provider, client, cfg.LLM_MODEL

        # Anthropic
        if provider == "anthropic":
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
                return provider, client, cfg.LLM_MODEL or "claude-3-5-haiku-20241022"
            except ImportError:
                logger.error("anthropic 未安装: pip install anthropic")
                return "none", None, None

        # OpenAI 兼容（包括 Ollama、vLLM、LM Studio、本地 API 等）
        if provider in ("openai", "openai_compatible", "ollama", "local", "lmstudio", "vllm"):
            try:
                from openai import OpenAI
                kwargs: Dict[str, Any] = {}
                api_key = cfg.LLM_API_KEY or ("ollama" if provider == "ollama" else "not-needed")
                kwargs["api_key"] = api_key
                if cfg.LLM_BASE_URL:
                    kwargs["base_url"] = cfg.LLM_BASE_URL
                client = OpenAI(**kwargs)
                return "openai", client, cfg.LLM_MODEL
            except ImportError:
                logger.error("openai 未安装: pip install openai")
                return "none", None, None

        logger.warning(f"[LLM] 未配置任何 LLM，将返回空响应。请在 .env 或设置页配置 LLM_API_KEY")
        return "none", None, None

    def complete(
        self,
        prompt: str,
        system: str = None,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """生成文本，自动适配不同 provider"""
        if not prompt or not prompt.strip():
            return ""

        provider, client, model = self._resolve()

        if provider == "none" or client is None:
            return ""

        def _filter_thinking(text: str) -> str:
            """过滤 <thinking> 标签内容"""
            text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            return text.strip()

        try:
            if provider == "anthropic":
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if system:
                    kwargs["system"] = system
                resp = client.messages.create(**kwargs)
                return _filter_thinking(resp.content[0].text.strip())

            else:  # openai / azure / openai_compatible
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return _filter_thinking(resp.choices[0].message.content.strip())

        except Exception as e:
            error_msg = str(e)
            # 检测余额不足错误
            if "insufficient_balance" in error_msg or "1008" in error_msg:
                logger.error(f"[LLM] API 余额不足: {error_msg}")
                return "[错误] LLM API 余额不足，请充值后重试"
            logger.error(f"[LLM] complete() 失败: {e}")
            return ""

    def __call__(self, prompt: str, **kwargs) -> str:
        return self.complete(prompt, **kwargs)

    def test_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接，返回状态信息（用于前端健康检查）"""
        provider, client, model = self._resolve()
        if provider == "none":
            return {"ok": False, "provider": "none", "error": "未配置 LLM"}
        try:
            result = self.complete("回复 OK", max_tokens=10)
            return {
                "ok": bool(result),
                "provider": provider,
                "model": model,
                "response": result[:20],
            }
        except Exception as e:
            return {"ok": False, "provider": provider, "model": model, "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Embedding Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Embedder:
    """
    统一 Embedding 封装
    支持：OpenAI / Azure OpenAI / Ollama（nomic-embed-text 等）/ 任意兼容端点
    原则：调用方必须传入 summary，严禁传入 raw_content（原则 2）
    """

    def _resolve(self):
        import config as cfg
        provider = (cfg.EMBEDDING_PROVIDER or cfg.LLM_PROVIDER or "").lower().strip()

        if not provider or provider == "auto":
            if cfg.LLM_BASE_URL:
                provider = "openai_compatible"
            elif cfg.LLM_API_KEY:
                provider = "openai"
            else:
                provider = "none"

        if provider == "azure":
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=cfg.LLM_API_KEY,
                api_version=cfg.AZURE_OPENAI_API_VERSION or "2024-02-01",
                azure_endpoint=cfg.LLM_BASE_URL,
            )
            return provider, client, cfg.EMBEDDING_MODEL

        if provider in ("openai", "openai_compatible", "ollama", "local", "lmstudio", "vllm"):
            try:
                from openai import OpenAI
                kwargs: Dict[str, Any] = {}
                kwargs["api_key"] = cfg.LLM_API_KEY or "not-needed"
                # 优先使用 EMBEDDING_BASE_URL（用于 embedding 专用端点），其次用 LLM_BASE_URL
                base_url = cfg.EMBEDDING_BASE_URL or cfg.LLM_BASE_URL
                if base_url:
                    kwargs["base_url"] = base_url
                client = OpenAI(**kwargs)
                return "openai", client, cfg.EMBEDDING_MODEL
            except ImportError:
                pass

        return "none", None, None

    def embed(self, text: str) -> List[float]:
        """生成单条 embedding（必须传 summary，原则 2）"""
        import config as cfg
        if not text or not text.strip():
            return [0.0] * cfg.EMBEDDING_DIM

        provider, client, model = self._resolve()

        if provider == "none" or client is None:
            logger.debug("[Embedder] 未配置 Embedding，使用哈希降级")
            return self._hash_embed(text)

        try:
            response = client.embeddings.create(
                model=model,
                input=text.strip(),
                encoding_format="float",
            )
            if response.data and len(response.data) > 0:
                return response.data[0].embedding
            logger.warning("[Embedder] 响应数据为空，使用哈希降级")
            return self._hash_embed(text)
        except Exception as e:
            error_msg = str(e)
            # 检测余额不足错误
            if "insufficient_balance" in error_msg or "1008" in error_msg:
                logger.error(f"[Embedder] API 余额不足: {error_msg}")
                return self._hash_embed(text)
            logger.error(f"[Embedder] embed() 失败: {e}")
            return self._hash_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量 embedding"""
        import config as cfg
        if not texts:
            return []
        provider, client, model = self._resolve()

        if provider == "none" or client is None:
            return [self._hash_embed(t) for t in texts]

        try:
            clean = [t.strip() for t in texts if t and t.strip()]
            if not clean:
                return [[0.0] * cfg.EMBEDDING_DIM] * len(texts)
            resp = client.embeddings.create(model=model, input=clean, encoding_format="float")
            if resp.data and len(resp.data) > 0:
                return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
            logger.warning("[Embedder] 批量响应数据为空，使用哈希降级")
            return [self._hash_embed(t) for t in texts]
        except Exception as e:
            error_msg = str(e)
            # 检测余额不足错误
            if "insufficient_balance" in error_msg or "1008" in error_msg:
                logger.error(f"[Embedder] API 余额不足: {error_msg}")
            else:
                logger.error(f"[Embedder] embed_batch() 失败: {e}")
            return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> List[float]:
        """哈希降级 embedding（开发/无 API 场景，保证同文本同向量）"""
        import config as cfg
        dim = cfg.EMBEDDING_DIM
        h = hashlib.sha256(text.encode()).digest()
        repeats = (dim * 4 + len(h) - 1) // len(h)
        raw = (h * repeats)[: dim * 4]
        floats = list(struct.unpack(f"{dim}f", raw))
        norm = sum(f**2 for f in floats) ** 0.5
        if norm > 0:
            floats = [f / norm for f in floats]
        return floats

    def test_connection(self) -> Dict[str, Any]:
        provider, client, model = self._resolve()
        if provider == "none":
            return {"ok": False, "provider": "none", "error": "未配置 Embedding"}
        try:
            vec = self.embed("test")
            return {"ok": len(vec) > 0, "provider": provider, "model": model, "dim": len(vec)}
        except Exception as e:
            return {"ok": False, "provider": provider, "model": model, "error": str(e)}


# ── 全局单例（每次调用都会重新读 config，支持热更新）────────────────────────
_llm: Optional[LLMClient] = None
_embedder: Optional[Embedder] = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


# 向后兼容旧模块的导入
def get_llm_client() -> LLMClient:
    return get_llm()
