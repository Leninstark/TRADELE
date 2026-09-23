"""Text embeddings for watchlist RAG (Gemini primary, hash fallback)."""
from __future__ import annotations

import hashlib
import logging
import struct
from typing import Optional

from TRADELE.config import settings

logger = logging.getLogger(__name__)
EMBED_DIM = 768


def _hash_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic pseudo-embedding when no API key (enables cosine ranking)."""
    out: list[float] = []
    seed = text.encode("utf-8")
    while len(out) < dim:
        h = hashlib.sha256(seed + struct.pack("<I", len(out))).digest()
        for i in range(0, len(h), 4):
            if len(out) >= dim:
                break
            chunk = h[i : i + 4]
            if len(chunk) == 4:
                val = struct.unpack("<i", chunk)[0] / 2147483647.0
                out.append(val)
        seed = h
    norm = sum(x * x for x in out) ** 0.5 or 1.0
    return [x / norm for x in out]


def embed_text(text: str) -> list[float]:
    content = (text or "").strip()[:8000]
    if not content:
        return _hash_embedding("empty")

    api_key = settings.gemini_api_key
    if api_key:
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=content,
                task_type="retrieval_document",
            )
            vec = result.get("embedding") if isinstance(result, dict) else getattr(result, "embedding", None)
            if vec and len(vec) >= 8:
                return [float(x) for x in vec[:EMBED_DIM]]
        except Exception as e:
            logger.debug("Gemini embedding failed: %s", e)

    if settings.openai_api_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key, base_url=settings.llm_base_url or None)
            resp = client.embeddings.create(model="text-embedding-3-small", input=content)
            vec = resp.data[0].embedding
            if vec:
                return [float(x) for x in vec[:EMBED_DIM]]
        except Exception as e:
            logger.debug("OpenAI embedding failed: %s", e)

    return _hash_embedding(content)


def embed_query(text: str) -> list[float]:
    return embed_text(f"query: {text}")
