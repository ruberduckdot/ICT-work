import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from src.config import get_settings
from src.llm import factory
from src.llm.mock import MockChatModel, select_tool


@tool
def rag_search(query: str) -> str:
    """재배 문서 검색"""
    return "ok"


@tool
def get_mushroom_price(period: str) -> str:
    """가격 조회"""
    return "ok"


def test_factory_returns_mock_by_default():
    assert get_settings().llm_provider == "mock"
    assert isinstance(factory.get_chat_model(), MockChatModel)
    assert factory.get_vision_model().mode == "vision"
    assert factory.describe_provider()["provider"] == "mock"


def test_mock_returns_tool_calls_in_standard_format():
    model = factory.get_chat_model().bind_tools([rag_search, get_mushroom_price])
    msg = model.invoke([HumanMessage(content="느타리버섯 적정 생육 온도 알려줘")])
    assert isinstance(msg, AIMessage)
    assert len(msg.tool_calls) == 1
    call = msg.tool_calls[0]
    assert call["name"] == "rag_search"
    assert call["args"] == {"query": "느타리버섯 적정 생육 온도 알려줘"}
    assert call["id"].startswith("call_")
    assert call.get("type") == "tool_call"


def test_mock_final_answer_after_tool_message():
    model = factory.get_chat_model().bind_tools([get_mushroom_price])
    first = model.invoke([HumanMessage(content="최근 가격 알려줘")])
    call = first.tool_calls[0]
    assert call["name"] == "get_mushroom_price" and call["args"]["period"] == "1m"
    final = model.invoke([
        HumanMessage(content="최근 가격 알려줘"), first,
        ToolMessage(content="도매 평균 5,000원", tool_call_id=call["id"], name=call["name"]),
    ])
    assert not final.tool_calls
    assert "도매 평균 5,000원" in final.content


@pytest.mark.parametrize("text,expected", [
    ("푸른곰팡이병 방제 방법", "rag_search"),
    ("오늘 일지 써줘", "write_farm_diary"),
    ("최근 가격 알려줘", "get_mushroom_price"),
    ("이 버섯 상태 봐줘\n[첨부 이미지 경로: outputs/uploads/a.jpg]", "analyze_mushroom_image"),
])
def test_select_tool_rules(text, expected):
    names = ["rag_search", "analyze_mushroom_image", "write_farm_diary", "get_mushroom_price"]
    assert select_tool(text, names)[0] == expected


def test_gemini_requires_key_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(factory.LLMConfigError):
        factory.get_chat_model()


def test_invoke_with_retry_backoff_then_unavailable():
    calls, sleeps = [], []

    class RateLimit(Exception):
        status_code = 429

    def boom():
        calls.append(1)
        raise RateLimit("429 Too Many Requests")

    with pytest.raises(factory.LLMUnavailableError):
        factory.invoke_with_retry(boom, sleep=sleeps.append)
    assert len(calls) == 3  # 최초 1회 + 재시도 2회
    assert sleeps == [1.0, 2.0]


def test_invoke_with_retry_non_retryable_raises_original():
    def bad():
        raise ValueError("schema")

    with pytest.raises(ValueError):
        factory.invoke_with_retry(bad, sleep=lambda s: None)
