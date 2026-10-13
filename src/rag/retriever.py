"""`manuals` 컬렉션 검색. 결과에는 출처(파일명, 페이지, 청크 id)와 유사도를 담는다."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import MANUALS_COLLECTION
from src.rag.embeddings import default_threshold, get_embeddings
from src.rag.ingest import ensure_index, get_store

NO_EVIDENCE = "문서 근거 없음"


@dataclass
class Hit:
    text: str
    source: str
    page: int
    chunk_id: str
    score: float
    is_sample: bool

    @property
    def citation(self) -> str:
        page = f" p.{self.page}" if self.page else ""
        return f"{self.source}{page} · {self.chunk_id.split('#')[-1]}"


def search(query: str, k: int = 4, threshold: float | None = None, persist_dir: Path | None = None) -> dict:
    """반환: {query, hits[list[dict]], threshold, backend, no_evidence(bool)}"""
    ensure_index(persist_dir)
    _, backend, fallback = get_embeddings()
    thr = default_threshold(backend) if threshold is None else threshold
    store = get_store(MANUALS_COLLECTION, persist_dir)
    raw = store.similarity_search_with_score(query, k=k)
    hits = []
    for doc, distance in raw:
        score = round(1.0 - float(distance), 4)  # cosine distance → similarity
        if score < thr:
            continue
        m = doc.metadata
        hits.append(Hit(doc.page_content, m.get("source", "?"), int(m.get("page", 0) or 0),
                        m.get("chunk_id", "?"), score, bool(m.get("is_sample", False))))
    return {"query": query, "hits": [asdict(h) | {"citation": h.citation} for h in hits], "threshold": thr,
            "backend": backend, "fallback_reason": fallback, "no_evidence": not hits}


def format_for_llm(result: dict, max_chars: int = 700) -> str:
    if result["no_evidence"]:
        return f"{NO_EVIDENCE}: '{result['query']}'와 관련된 재배 문서 구절을 찾지 못함 (유사도 임계값 {result['threshold']})."
    lines = [f"검색어: {result['query']} / 검색 결과 {len(result['hits'])}건"]
    for i, h in enumerate(result["hits"], 1):
        # 청크 안의 Markdown 제목(#)·인용(>) 기호는 답변 렌더링을 깨뜨리므로 제거
        text = re.sub(r"(^|\s)(#{1,6}|>)\s+", r"\1", h["text"].strip()).replace("\n", " ")
        lines.append(f"[{i}] 출처: {h['citation']} · 유사도 {h['score']:.3f}\n\n{text[:max_chars]}")
    lines.append("답변 시 위 [번호]와 출처를 인용할 것.")
    return "\n\n".join(lines)
