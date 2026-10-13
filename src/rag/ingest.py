"""문서 → 청킹 → Embedding → Chroma(`manuals`).

문서 우선순위: data/raw/docs/*.pdf|*.md → (없으면) data/sample/docs/*.md
재색인: python -m src.rag.ingest
"""
from __future__ import annotations

import argparse
import logging
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import ANALYSIS_COLLECTION, DATA_RAW, DATA_SAMPLE, MANUALS_COLLECTION, VECTORSTORE_DIR
from src.rag.embeddings import get_embeddings

log = logging.getLogger(__name__)

CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


@lru_cache(maxsize=4)
def get_client(path: str):
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))


def get_store(collection: str = MANUALS_COLLECTION, persist_dir: Path | None = None) -> Chroma:
    emb, backend, _ = get_embeddings()
    return Chroma(
        collection_name=collection,
        embedding_function=emb,
        client=get_client(str(persist_dir or VECTORSTORE_DIR)),
        collection_metadata={"hnsw:space": "cosine", "embedding_backend": backend},
    )


def collection_backend(store: Chroma) -> str | None:
    return (store._collection.metadata or {}).get("embedding_backend")


def collection_count(store: Chroma) -> int:
    return store._collection.count()


def discover_docs(raw_dir: Path | None = None, sample_dir: Path | None = None) -> tuple[list[Path], bool]:
    """(문서 경로 목록, 샘플 여부)."""
    raw_dir = raw_dir or DATA_RAW / "docs"
    sample_dir = sample_dir or DATA_SAMPLE / "docs"
    raw = sorted(p for ext in ("*.pdf", "*.md") for p in raw_dir.glob(ext))
    if raw:
        return raw, False
    return sorted(sample_dir.glob("*.md")), True


def load_documents(paths: list[Path], is_sample: bool) -> list[Document]:
    docs: list[Document] = []
    for p in paths:
        if p.suffix.lower() == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader

            for d in PyPDFLoader(str(p)).load():
                page = int(d.metadata.get("page", 0)) + 1  # 1부터 시작하는 페이지 번호
                docs.append(Document(page_content=d.page_content,
                                     metadata={"source": p.name, "page": page, "is_sample": is_sample}))
        else:
            docs.append(Document(page_content=p.read_text(encoding="utf-8"),
                                 metadata={"source": p.name, "page": 0, "is_sample": is_sample}))
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    counters: dict[tuple, int] = {}
    for c in chunks:
        key = (c.metadata["source"], c.metadata["page"])
        counters[key] = counters.get(key, 0) + 1
        page = c.metadata["page"]
        c.metadata["chunk_id"] = f"{c.metadata['source']}#{'p' + str(page) + '-' if page else ''}c{counters[key]}"
    return chunks


def ingest(persist_dir: Path | None = None, raw_dir: Path | None = None, sample_dir: Path | None = None) -> dict:
    """`manuals` 컬렉션을 비우고 다시 색인한다."""
    paths, is_sample = discover_docs(raw_dir, sample_dir)
    client = get_client(str(persist_dir or VECTORSTORE_DIR))
    if MANUALS_COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(MANUALS_COLLECTION)
    store = get_store(MANUALS_COLLECTION, persist_dir)
    chunks = split_documents(load_documents(paths, is_sample))
    if chunks:
        store.add_documents(chunks, ids=[c.metadata["chunk_id"] for c in chunks])
    _, backend, fallback = get_embeddings()
    return {"files": [p.name for p in paths], "is_sample": is_sample, "chunks": len(chunks),
            "embedding_backend": backend, "fallback_reason": fallback}


def ensure_index(persist_dir: Path | None = None) -> dict | None:
    """비어 있거나 Embedding 백엔드가 바뀐 경우에만 색인. 색인했으면 결과 dict 반환."""
    store = get_store(MANUALS_COLLECTION, persist_dir)
    _, backend, _ = get_embeddings()
    if collection_count(store) == 0 or collection_backend(store) != backend:
        return ingest(persist_dir)
    return None


def reset_analysis_logs(persist_dir: Path | None = None) -> None:
    client = get_client(str(persist_dir or VECTORSTORE_DIR))
    if ANALYSIS_COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(ANALYSIS_COLLECTION)


def main() -> None:
    parser = argparse.ArgumentParser(description="재배 매뉴얼 재색인")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = ingest()
    print(f"색인 완료: 파일 {result['files']} / 청크 {result['chunks']}개 / 샘플={result['is_sample']}")
    print(f"Embedding: {result['embedding_backend']}")
    if result["fallback_reason"]:
        print(f"[경고] 실모델 로드 실패로 해싱 폴백 사용: {result['fallback_reason']}")


if __name__ == "__main__":
    main()
