"""
tools/embedder.py
向后兼容封装 — 所有实现已迁移到 tools/llm.py
"""
from tools.llm import LLMClient, Embedder, get_llm, get_embedder, get_llm_client

__all__ = ["LLMClient", "Embedder", "get_llm", "get_embedder", "get_llm_client"]
