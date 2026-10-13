"""영농일지 작성. 정해진 Markdown 양식(날짜/환경/생육 상태/병해충/작업 내용/익일 계획)을 채우고
'익일 계획'만 LLM으로 생성한다. 결과는 outputs/diary/YYYY-MM-DD.md로 저장한다."""
from __future__ import annotations

import logging
import re
from datetime import date as date_cls
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import DIARY_DIR, get_settings
from src.llm.factory import LLMConfigError, LLMUnavailableError, UNAVAILABLE_MESSAGE, get_text_model, invoke_with_retry

log = logging.getLogger(__name__)

PLAN_SYSTEM = """당신은 느타리버섯 재배 농가의 영농일지 작성을 돕는다.
입력된 환경값·생육 상태·병해충·작업 내용만 근거로 '익일 계획'을 3~5개 글머리표(- )로 작성한다.
입력에 없는 측정값이나 수치를 만들어내지 않는다. 권장 범위 수치가 필요하면 '재배 매뉴얼 확인 필요'라고 쓴다."""

ENV_PATTERNS = {
    "temperature": r"(?:온도|기온)\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
    "humidity": r"습도\s*[:=]?\s*(\d+(?:\.\d+)?)",
    "co2": r"(?:CO2|co2|이산화탄소)\s*[:=]?\s*(\d+(?:\.\d+)?)",
}


def parse_env_from_text(text: str) -> dict[str, float | None]:
    """메모에서 '온도 16', '습도 90%', 'CO2 900ppm' 형태의 값을 추출."""
    out: dict[str, float | None] = {}
    for key, pat in ENV_PATTERNS.items():
        m = re.search(pat, text or "")
        out[key] = float(m.group(1)) if m else None
    return out


def _fmt(v: float | None, unit: str) -> str:
    return "미입력" if v is None else f"{v:g} {unit}"


def _analysis_lines(analyses: list[dict], field: str) -> list[str]:
    lines = []
    for rec in analyses:
        r = rec["result"]
        mock = " · mock(실제 분석 아님)" if rec.get("is_mock") else ""
        lines.append(f"- {rec['file_name']} ({rec['analyzed_at']}): **{r[field]}** "
                     f"(신뢰도 {r['confidence']:.2f}{mock})")
    return lines or ["- 기록 없음 (당일 이미지 분석 결과 미선택)"]


def generate_plan(context: str) -> str:
    try:
        model = get_text_model()
        msg = invoke_with_retry(lambda: model.invoke([SystemMessage(content=PLAN_SYSTEM),
                                                      HumanMessage(content=context)]))
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        return text.strip()
    except LLMUnavailableError:
        return f"- 익일 계획 자동 생성 실패: {UNAVAILABLE_MESSAGE}"
    except LLMConfigError as exc:
        return f"- 익일 계획 자동 생성 실패: {exc}"


def build_diary(day: str, temperature: float | None, humidity: float | None, co2: float | None,
                notes: str, analyses: list[dict] | None = None) -> str:
    analyses = analyses or []
    env_table = (
        "| 항목 | 측정값 |\n|---|---|\n"
        f"| 온도 | {_fmt(temperature, '℃')} |\n| 상대습도 | {_fmt(humidity, '%')} |\n| CO2 | {_fmt(co2, 'ppm')} |"
    )
    growth = "\n".join(_analysis_lines(analyses, "growth_stage"))
    disease = "\n".join(_analysis_lines(analyses, "disease_suspected"))
    evidence = [f"  - 관찰 근거({a['file_name']}): {'; '.join(a['result']['visual_evidence'])}"
                for a in analyses if a["result"]["visual_evidence"]]
    work = notes.strip() or "기록 없음"
    context = (f"날짜: {day}\n환경: 온도 {_fmt(temperature, '℃')}, 습도 {_fmt(humidity, '%')}, CO2 {_fmt(co2, 'ppm')}\n"
               f"생육 상태:\n{growth}\n병해충:\n{disease}\n작업 내용: {work}")
    plan = generate_plan(context)
    s = get_settings()
    author = "mock 모델(데모 모드, 고정 문구)" if s.is_mock else f"{s.llm_provider} / {s.llm_model}"
    return f"""# 영농일지 — {day}

## 1. 날짜
{day}

## 2. 재배사 환경
{env_table}

## 3. 생육 상태
{growth}

## 4. 병해충
{disease}
{chr(10).join(evidence)}

## 5. 작업 내용
{work}

## 6. 익일 계획
{plan}

---
*작성: 느타리버섯 스마트 농업 AI · 익일 계획 생성 모델: {author}*
"""


def save_diary(day: str, markdown: str, out_dir: Path | None = None) -> Path:
    date_cls.fromisoformat(day)  # 형식 검증 (YYYY-MM-DD)
    out_dir = out_dir or DIARY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
