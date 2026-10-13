"""로컬 Embedding.

- 기본: sentence-transformers (`EMBEDDING_MODEL`, 기본 intfloat/multilingual-e5-small, BAAI/bge-m3 전환 가능)
  e5 계열은 질의에 `query: `, 문서에 `passage: ` 접두어를 붙인다.
- 폴백: sentence-transformers/torch가 없거나 모델을 내려받지 못하면 문자 n-gram 해싱 Embedding을 쓴다.
  의미 유사도가 아닌 어휘 겹침 기반이므로 품질이 낮다. `EMBEDDING_MODEL=hash`로 명시 선택도 가능.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from src.config import get_settings

log = logging.getLogger(__name__)
HASH_BACKEND = "hash-bigram-1024"


class E5SentenceTransformerEmbeddings(Embeddings):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # torch 필요

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")
        self.use_prefix = "e5" in model_name.lower()

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" if self.use_prefix else t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}" if self.use_prefix else text])[0]


class HashingEmbeddings(Embeddings):
    """토큰 내부 문자 bigram 해싱 + log(1+tf) + L2 정규화. 외부 다운로드 없이 동작하는 폴백.

    설정은 샘플 문서에서 관련 질의(최소 0.188)와 무관 질의(최대 0.067)의 분리도가 가장 큰 조합으로 고름.
    """

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for token in re.findall(r"[0-9a-z가-힣]+", text.lower()):
            for i in range(len(token) - 1):
                h = int.from_bytes(hashlib.md5(token[i:i + 2].encode()).digest()[:4], "little")
                v[h % self.dim] += 1.0
        v = [math.log1p(x) for x in v]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@lru_cache(maxsize=4)
def _load(model_name: str) -> tuple[Embeddings, str, str | None]:
    if model_name.lower() == "hash":
        return HashingEmbeddings(), HASH_BACKEND, None
    try:
        return E5SentenceTransformerEmbeddings(model_name), model_name, None
    except Exception as exc:  # noqa: BLE001 - ImportError, 다운로드 실패 등
        reason = f"{type(exc).__name__}: {str(exc)[:160]}"
        log.warning("Embedding 모델 %s 로드 실패 → 해싱 폴백 사용 (%s)", model_name, reason)
        return HashingEmbeddings(), HASH_BACKEND, reason


def get_embeddings() -> tuple[Embeddings, str, str | None]:
    """(embeddings, backend_id, fallback_reason). backend_id는 색인 호환성 판정에 사용."""
    return _load(get_settings().embedding_model)


def default_threshold(backend_id: str) -> float:
    """유사도 임계값. 실모델은 RAG_SCORE_THRESHOLD, 해싱 폴백은 어휘 겹침 기준의 낮은 값."""
    if backend_id == HASH_BACKEND:
        return 0.12  # 폴백 전용 경험값 (샘플 문서 기준으로만 조정됨)
    return get_settings().rag_score_threshold
