import pytest

from src.rag import ingest, retriever
from src.rag.embeddings import HASH_BACKEND, HashingEmbeddings, get_embeddings


@pytest.fixture(scope="module")
def store_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("vs")
    result = ingest.ingest(persist_dir=d, raw_dir=d / "no_raw")
    assert result["is_sample"] and result["chunks"] > 0
    return d


@pytest.mark.parametrize("query,expected_word", [
    ("적정 생육 온도", "온도"),
    ("푸른곰팡이병 방제", "푸른곰팡이"),
    ("환기 관리", "환기"),
])
def test_sample_queries_return_sources(store_dir, query, expected_word):
    res = retriever.search(query, persist_dir=store_dir)
    assert not res["no_evidence"]
    top = res["hits"][0]
    assert top["source"] == "oyster_mushroom_guide.md" and top["chunk_id"].startswith("oyster_mushroom_guide.md#c")
    assert expected_word in top["text"]
    text = retriever.format_for_llm(res)
    assert "출처: oyster_mushroom_guide.md" in text


def test_unrelated_query_returns_no_evidence(store_dir):
    res = retriever.search("자동차 엔진오일 교체 주기", persist_dir=store_dir)
    assert res["no_evidence"]
    assert retriever.format_for_llm(res).startswith(retriever.NO_EVIDENCE)


def test_chunk_size_and_metadata(tmp_path):
    paths, is_sample = ingest.discover_docs(tmp_path, None)
    chunks = ingest.split_documents(ingest.load_documents(paths, is_sample))
    assert all(len(c.page_content) <= ingest.CHUNK_SIZE for c in chunks)
    assert len({c.metadata["chunk_id"] for c in chunks}) == len(chunks)


def test_e5_prefix_applied(monkeypatch):
    from src.rag import embeddings as E

    seen = []

    class Fake(E.E5SentenceTransformerEmbeddings):
        def __init__(self):
            self.use_prefix = True

        def _encode(self, texts):
            seen.extend(texts)
            return [[0.0] for _ in texts]

    f = Fake()
    f.embed_query("온도")
    f.embed_documents(["본문"])
    assert seen == ["query: 온도", "passage: 본문"]


def test_hash_embedding_fallback_is_normalized():
    v = HashingEmbeddings().embed_query("느타리버섯 온도")
    assert abs(sum(x * x for x in v) - 1.0) < 1e-6
    _, backend, _ = get_embeddings()
    assert backend  # 실모델 또는 HASH_BACKEND
    assert isinstance(HASH_BACKEND, str)
