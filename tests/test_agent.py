from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from src.agent import graph, tools
from src.llm.mock import MockChatModel


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    from src.diary import writer
    from src.rag import ingest
    from src.vision import analyzer

    monkeypatch.setattr(ingest, "VECTORSTORE_DIR", tmp_path / "vs")
    monkeypatch.setattr(analyzer, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(writer, "DIARY_DIR", tmp_path / "diary")
    upload = tmp_path / "uploads"
    upload.mkdir()
    monkeypatch.setattr(tools, "ALLOWED_IMAGE_DIRS", (upload,))
    return tmp_path


def _run(question, image_path=None):
    res = graph.run_agent(question, image_path=image_path)
    assert res["error"] is None, res["answer"]
    return res


def test_document_query_calls_rag_search():
    res = _run("푸른곰팡이병 방제 방법 알려줘")
    assert [t["tool"] for t in res["trace"]] == ["rag_search"]
    art = res["trace"][0]["artifact"]
    assert not art["no_evidence"] and art["hits"][0]["source"] == "oyster_mushroom_guide.md"
    assert "출처: oyster_mushroom_guide.md" in res["answer"]


def test_image_question_calls_analyze(isolated_paths):
    img = isolated_paths / "uploads" / "mock_test_dummy.png"
    Image.new("RGB", (32, 32), (200, 200, 190)).save(img)
    res = _run("이 버섯 상태 어때?", image_path=str(img))
    assert [t["tool"] for t in res["trace"]] == ["analyze_mushroom_image"]
    t = res["trace"][0]
    assert t["args"]["image_path"] == str(img)
    assert t["artifact"]["result"]["growth_stage"] == "판단불가"


def test_diary_request_calls_write_farm_diary(isolated_paths):
    res = _run("오늘 일지 써줘. 온도 16도 습도 90% CO2 900ppm, 3동 환기 2회 실시")
    assert [t["tool"] for t in res["trace"]] == ["write_farm_diary"]
    art = res["trace"][0]["artifact"]
    path = Path(art["path"])
    assert path.exists() and path.parent == isolated_paths / "diary"
    md = path.read_text(encoding="utf-8")
    for heading in ("## 1. 날짜", "## 2. 재배사 환경", "## 3. 생육 상태", "## 4. 병해충", "## 5. 작업 내용", "## 6. 익일 계획"):
        assert heading in md
    assert "16 ℃" in md and "90 %" in md and "900 ppm" in md


def test_price_query_calls_get_mushroom_price():
    res = _run("최근 가격 알려줘")
    assert [t["tool"] for t in res["trace"]] == ["get_mushroom_price"]
    art = res["trace"][0]["artifact"]
    assert art["period"] == "1m" and {r["market"] for r in art["rows"]} == {"도매", "소매"}
    assert "SAMPLE" in res["answer"]


def test_iteration_limit_six():
    calls = []

    class Looping(MockChatModel):
        def _respond(self, messages):
            calls.append(bool(self.bound_tool_names))
            if self.bound_tool_names:
                return AIMessage(content="", tool_calls=[{"name": "get_mushroom_price", "args": {"period": "1w"},
                                                          "id": f"call_{len(calls)}", "type": "tool_call"}])
            return AIMessage(content="최종 답변")

    model = Looping()
    res = graph.run_agent("가격", agent=graph.build_agent(model=model))
    assert res["iterations"] == 6 and calls == [True] * 5 + [False]  # 마지막 6회차는 Tool 없이 최종 답변
    assert len(res["trace"]) == 5 and res["answer"] == "최종 답변"


def test_unavailable_model_returns_message(monkeypatch):
    class Down(MockChatModel):
        def _respond(self, messages):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr("src.llm.factory.time.sleep", lambda s: None)
    res = graph.run_agent("온도", agent=graph.build_agent(model=Down()))
    assert res["error"] and "API 한도 초과 또는 모델 서버 미연결" in res["answer"]


def test_image_path_outside_allowed_dirs_rejected(tmp_path):
    with pytest.raises(ValueError):
        tools._resolve_image("/etc/passwd")
