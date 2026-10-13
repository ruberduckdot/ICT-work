import json

import pytest
from PIL import Image

from src.llm.mock import MockChatModel
from src.vision import analyzer


@pytest.fixture
def dummy_image(tmp_path):
    p = tmp_path / "mock_test_dummy.png"
    Image.new("RGB", (32, 32), (120, 130, 110)).save(p)
    return p


def test_schema_and_cache(dummy_image, tmp_path):
    cache, vs = tmp_path / "cache", tmp_path / "vs"
    first = analyzer.analyze_image(dummy_image, cache_dir=cache, persist_dir=vs)
    analyzer.MushroomAnalysis.model_validate(first["result"])  # 스키마 준수
    assert first["cached"] is False and first["parse_status"] == "ok"
    assert first["result"]["growth_stage"] == "판단불가"
    assert len(first["sha256"]) == 64
    files = list(cache.glob("*.json"))
    assert len(files) == 1 and files[0].name.startswith(first["sha256"])

    model = MockChatModel(mode="vision")
    second = analyzer.analyze_image(dummy_image, cache_dir=cache, persist_dir=vs, model=model)
    assert second["cached"] is True and model.call_count == 0  # 재호출 없음
    assert second["result"] == first["result"]


def test_analysis_logged_to_chroma(dummy_image, tmp_path):
    from src.config import ANALYSIS_COLLECTION
    from src.rag.ingest import get_store

    vs = tmp_path / "vs"
    rec = analyzer.analyze_image(dummy_image, cache_dir=tmp_path / "c", persist_dir=vs)
    got = get_store(ANALYSIS_COLLECTION, vs)._collection.get(ids=[rec["cache_key"]])
    assert got["ids"] == [rec["cache_key"]]
    meta = got["metadatas"][0]
    assert meta["file_name"] == dummy_image.name and meta["growth_stage"] == "판단불가"
    assert "analyzed_at" in meta


def test_retry_once_then_success(dummy_image, tmp_path):
    valid = json.dumps({"growth_stage": "수확적기", "disease_suspected": "정상", "confidence": 0.8,
                        "visual_evidence": ["갓 가장자리 말림"], "recommended_actions": ["수확"],
                        "summary_ko": "수확 적기"}, ensure_ascii=False)
    model = MockChatModel(mode="vision", scripted_responses=["이건 JSON이 아님", valid])
    rec = analyzer.analyze_image(dummy_image, cache_dir=tmp_path, log_vector=False, model=model)
    assert model.call_count == 2 and rec["parse_status"] == "retried"
    assert rec["result"]["growth_stage"] == "수확적기"


def test_two_failures_return_unknown_and_not_cached(dummy_image, tmp_path):
    model = MockChatModel(mode="vision", scripted_responses=["bad", '{"growth_stage": "모름"}'])
    rec = analyzer.analyze_image(dummy_image, cache_dir=tmp_path, log_vector=False, model=model)
    assert model.call_count == 2 and rec["parse_status"] == "failed"
    assert rec["result"]["growth_stage"] == "판단불가" and rec["result"]["confidence"] == 0.0
    assert not list(tmp_path.glob("*.json"))


def test_parse_handles_code_fence():
    text = '```json\n{"growth_stage":"원기형성","disease_suspected":"정상","confidence":0.5,"summary_ko":"x"}\n```'
    assert analyzer.parse_analysis(text).growth_stage == "원기형성"
    assert analyzer.parse_analysis('{"growth_stage":"원기형성","disease_suspected":"정상","confidence":1.5,"summary_ko":"x"}') is None
