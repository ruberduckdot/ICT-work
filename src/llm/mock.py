"""키 없이 동작하는 Fake Chat 모델 (LLM_PROVIDER=mock).

- agent 모드: 키워드 규칙으로 Tool을 골라 실제 모델과 같은 형식의
  `AIMessage(tool_calls=[...])`를 반환한다. Tool 결과(ToolMessage)를 받으면
  결과를 묶어 고정 형식의 최종 답변을 만든다.
- vision 모드: 이미지를 실제로 분석하지 않고, 스키마에 맞는 '판단불가' JSON을 반환한다.
- text 모드: 고정 문구를 반환한다.

mock 응답은 시연·테스트용이며 실제 분석 결과가 아님을 응답 본문에 표기한다.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta
from typing import Any, Literal, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

MOCK_TAG = "[데모 모드 · mock 모델 응답]"

IMAGE_PATH_RE = re.compile(r"\[첨부 이미지 경로:\s*([^\]]+?)\s*\]")
IMAGE_FILE_RE = re.compile(r"([\w./\\:-]+\.(?:jpg|jpeg|png|webp))", re.IGNORECASE)
DATE_RE = re.compile(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})")

DIARY_KEYWORDS = ("일지", "영농일지", "기록해", "기록 해")
PRICE_KEYWORDS = ("가격", "시세", "얼마", "단가", "경락가")
IMAGE_KEYWORDS = ("사진", "이미지", "분석해")


def _text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _detect_period(text: str) -> str:
    rules = [
        (("일주일", "1주", "한 주", "이번 주", "최근 7일"), "1w"),
        (("3개월", "석 달", "분기"), "3m"),
        (("6개월", "반년"), "6m"),
        (("1년", "올해", "연간", "일년", "12개월"), "1y"),
        (("전체", "전 기간", "모든 기간"), "all"),
    ]
    for keys, period in rules:
        if any(k in text for k in keys):
            return period
    return "1m"


def _detect_date(text: str) -> str:
    m = DATE_RE.search(text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return date(y, mo, d).isoformat()
    if "어제" in text:
        return (date.today() - timedelta(days=1)).isoformat()
    return date.today().isoformat()


def _strip_attachment(text: str) -> str:
    return IMAGE_PATH_RE.sub("", text).strip()


def select_tool(text: str, available: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
    """사용자 입력에서 호출할 Tool과 인자를 키워드 규칙으로 결정한다."""
    available = set(available)
    question = _strip_attachment(text)

    image_match = IMAGE_PATH_RE.search(text) or IMAGE_FILE_RE.search(text)
    wants_diary = any(k in question for k in DIARY_KEYWORDS)
    wants_price = any(k in question for k in PRICE_KEYWORDS)

    if wants_diary and "write_farm_diary" in available:
        return "write_farm_diary", {"date": _detect_date(question), "notes": question}
    if image_match and "analyze_mushroom_image" in available:
        return "analyze_mushroom_image", {
            "image_path": image_match.group(1).strip(),
            "question": question or "이미지의 생육 상태와 병해충 여부를 분석해줘",
        }
    if wants_price and "get_mushroom_price" in available:
        return "get_mushroom_price", {"period": _detect_period(question)}
    if "rag_search" in available and question:
        return "rag_search", {"query": question}
    return None


MOCK_VISION_RESULT = {
    "growth_stage": "판단불가",
    "disease_suspected": "판단불가",
    "confidence": 0.0,
    "visual_evidence": ["mock 모델은 이미지를 실제로 관찰하지 않음"],
    "recommended_actions": ["실모델(LLM_PROVIDER=gemini 또는 ollama)로 재분석 필요"],
    "summary_ko": f"{MOCK_TAG} 이미지를 실제로 분석하지 않았으므로 판단불가로 반환함.",
}


class MockChatModel(BaseChatModel):
    """키워드 규칙 기반 Fake Chat 모델."""

    mode: Literal["agent", "vision", "text"] = "agent"
    bound_tool_names: list[str] = []
    # 테스트용: 지정 시 순서대로 이 문자열을 응답으로 반환
    scripted_responses: list[str] | None = None
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "mock-chat"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any):
        names = [getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools]
        return self.model_copy(update={"bound_tool_names": names})

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.call_count += 1
        message = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        if self.scripted_responses:
            idx = min(self.call_count - 1, len(self.scripted_responses) - 1)
            return AIMessage(content=self.scripted_responses[idx])

        if self.mode == "vision":
            return AIMessage(content=json.dumps(MOCK_VISION_RESULT, ensure_ascii=False))

        last_human_idx = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
        )
        if last_human_idx < 0:
            return AIMessage(content=f"{MOCK_TAG} 입력 메시지가 없음.")
        tool_results = [m for m in messages[last_human_idx + 1:] if isinstance(m, ToolMessage)]

        if tool_results:
            return AIMessage(content=self._final_answer(tool_results))

        if self.mode == "agent" and self.bound_tool_names:
            picked = select_tool(_text_of(messages[last_human_idx]), self.bound_tool_names)
            if picked:
                name, args = picked
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": name,
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "tool_call",
                    }],
                )

        return AIMessage(
            content=f"{MOCK_TAG} 실모델이 연결되지 않아 고정 응답을 반환함. "
            "LLM_PROVIDER를 gemini 또는 ollama로 설정하면 실제 생성 결과를 받을 수 있음."
        )

    @staticmethod
    def _final_answer(tool_results: list[ToolMessage]) -> str:
        lines = [MOCK_TAG, "아래는 호출한 도구의 결과를 그대로 정리한 것임 (LLM 요약 아님)."]
        for tm in tool_results:
            body = tm.content if isinstance(tm.content, str) else str(tm.content)
            if len(body) > 1500:
                body = body[:1500] + " …(생략)"
            lines.append(f"\n**도구: {tm.name}**\n\n{body}")
        return "\n".join(lines)
