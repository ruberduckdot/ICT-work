"""LangGraph Agent: agent 노드 ↔ ToolNode 순환. 최대 반복 6회.

사용자 입력에 따라 모델이 Tool을 고르고(tool_calls), ToolNode가 실행한 결과를 다시 모델에 넘긴다.
마지막 반복에서는 Tool 없이 최종 답변만 생성하게 해 반복 횟수를 제한한다.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.agent.tools import ALL_TOOLS
from src.config import AGENT_MAX_ITERATIONS
from src.llm.factory import LLMConfigError, LLMUnavailableError, UNAVAILABLE_MESSAGE, get_chat_model, invoke_with_retry

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 느타리버섯 재배 농가를 돕는 스마트 농업 상담 Agent다. 한국어로 답한다.
도구 선택 규칙:
- 재배 방법·환경(온도/습도/CO2/환기)·병해충 방제·문서 요약 질문 → rag_search
- 메시지에 '[첨부 이미지 경로: ...]'가 있고 이미지 상태를 묻는 경우 → analyze_mushroom_image(image_path=그 경로 그대로)
- 영농일지 작성 요청("일지 써줘" 등) → write_farm_diary(date=YYYY-MM-DD, notes=사용자 메모)
- 가격·시세 질문 → get_mushroom_price(period=1w|1m|3m|6m|1y|all)
답변 규칙:
- rag_search 결과를 쓸 때는 [번호]와 출처(파일명·페이지/청크)를 답변 끝에 반드시 표기한다.
- 도구 결과가 '문서 근거 없음'이면 추측으로 답하지 말고 문서 근거가 없다고 밝힌다.
- 도구 결과에 없는 수치·통계·약제명을 만들어내지 않는다.
- 가격 데이터 출처가 SAMPLE이면 실제 시세가 아니라고 명시한다.
- 이미지 분석 결과가 판단불가이거나 신뢰도가 낮으면 그 사실을 그대로 전달한다."""

FINAL_ONLY_NOTE = "도구 호출 한도에 도달함. 지금까지의 도구 결과만으로 최종 답변을 작성하라."
HISTORY_LIMIT = 6


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iterations: int


def build_agent(model=None, tools=None, max_iterations: int = AGENT_MAX_ITERATIONS):
    tools = tools or ALL_TOOLS
    base = model or get_chat_model()
    with_tools = base.bind_tools(tools)

    def agent_node(state: AgentState) -> dict[str, Any]:
        n = state.get("iterations", 0)
        last_round = n >= max_iterations - 1
        system = SYSTEM_PROMPT + (f"\n\n{FINAL_ONLY_NOTE}" if last_round else "")
        msgs = [SystemMessage(content=system), *state["messages"]]
        runnable = base if last_round else with_tools
        response = invoke_with_retry(lambda: runnable.invoke(msgs))
        return {"messages": [response], "iterations": n + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls and state["iterations"] < max_iterations:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def build_user_message(question: str, image_path: str | None = None) -> HumanMessage:
    text = question.strip()
    if image_path:
        text += f"\n\n[첨부 이미지 경로: {image_path}]"
    return HumanMessage(content=text)


def _summarize(content: Any, limit: int = 300) -> str:
    text = content if isinstance(content, str) else str(content)
    return text if len(text) <= limit else text[:limit] + " …"


def extract_trace(messages: list[BaseMessage]) -> list[dict]:
    """도구 호출 이력: 도구명, 입력, 결과 요약, artifact."""
    calls: dict[str, dict] = {}
    order: list[str] = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = {"tool": tc["name"], "args": tc["args"], "result": None, "artifact": None}
                order.append(tc["id"])
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls:
            calls[m.tool_call_id].update(result=_summarize(m.content), full_result=m.content,
                                         artifact=getattr(m, "artifact", None), status=getattr(m, "status", "success"))
    return [calls[i] for i in order]


def run_agent(question: str, image_path: str | None = None, history: list[BaseMessage] | None = None,
              agent=None) -> dict:
    """반환: {answer, trace, error, messages(이번 턴 Human+최종 AI)}"""
    user_msg = build_user_message(question, image_path)
    prior = list(history or [])[-HISTORY_LIMIT:]
    try:
        agent = agent or build_agent()
        state = agent.invoke({"messages": [*prior, user_msg], "iterations": 0},
                             config={"recursion_limit": AGENT_MAX_ITERATIONS * 2 + 2})
    except LLMUnavailableError:
        return {"answer": UNAVAILABLE_MESSAGE, "trace": [], "error": UNAVAILABLE_MESSAGE, "messages": []}
    except LLMConfigError as exc:
        return {"answer": f"모델 설정 오류: {exc}", "trace": [], "error": str(exc), "messages": []}
    except Exception as exc:  # noqa: BLE001 - UI가 죽지 않도록 모든 예외를 메시지로 변환
        log.exception("Agent 실행 실패")
        return {"answer": f"처리 중 오류가 발생함: {type(exc).__name__}", "trace": [], "error": str(exc), "messages": []}

    new_msgs = state["messages"][len(prior):]
    final = next((m for m in reversed(new_msgs) if isinstance(m, AIMessage) and not m.tool_calls), None)
    answer = final.content if final is not None else "최종 답변을 생성하지 못함"
    if not isinstance(answer, str):
        answer = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in answer)
    return {"answer": answer, "trace": extract_trace(new_msgs), "error": None,
            "iterations": state.get("iterations", 0),
            "messages": [user_msg, AIMessage(content=answer)]}
