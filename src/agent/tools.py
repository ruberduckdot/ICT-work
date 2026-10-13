"""Agent Tool 4종. 모두 (LLM용 텍스트, UI용 artifact) 쌍을 반환한다(content_and_artifact)."""
from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

from langchain_core.tools import tool

from src.config import DATA_RAW, DATA_SAMPLE, ROOT, UPLOAD_DIR
from src.data import loaders
from src.diary import writer
from src.llm.factory import LLMUnavailableError, UNAVAILABLE_MESSAGE
from src.rag import retriever
from src.vision import analyzer

ALLOWED_IMAGE_DIRS = (UPLOAD_DIR, DATA_RAW / "images", DATA_SAMPLE / "images")
PERIODS = ("1w", "1m", "3m", "6m", "1y", "all")


def _resolve_image(image_path: str) -> Path:
    p = Path(image_path)
    p = (ROOT / p).resolve() if not p.is_absolute() else p.resolve()
    if not any(p.is_relative_to(d.resolve()) for d in ALLOWED_IMAGE_DIRS):
        raise ValueError(f"허용되지 않은 이미지 경로: {image_path} (outputs/uploads, data/raw/images, data/sample/images만 허용)")
    if not p.exists():
        raise FileNotFoundError(f"이미지 파일 없음: {image_path}")
    return p


@tool(response_format="content_and_artifact")
def rag_search(query: str):
    """느타리버섯 재배 매뉴얼에서 관련 구절을 검색한다. 재배 환경(온도·습도·CO2·환기), 재배 단계,
    병해충 방제 등 재배 지식 질문과 문서 요약 요청에 사용한다. 결과에는 출처(파일명·페이지·청크)가 포함된다.

    Args:
        query: 검색할 질문 또는 키워드 (한국어)
    """
    result = retriever.search(query)
    return retriever.format_for_llm(result), {"type": "rag", **result}


@tool(response_format="content_and_artifact")
def analyze_mushroom_image(image_path: str, question: str = ""):
    """업로드된 느타리버섯 이미지의 생육 단계와 병해충 의심 여부를 VLM으로 분석한다.
    사용자 메시지에 '[첨부 이미지 경로: ...]'가 있을 때 그 경로를 그대로 넣는다.

    Args:
        image_path: 이미지 파일 경로 (예: outputs/uploads/xxx.jpg)
        question: 이미지에 대한 사용자 질문
    """
    path = _resolve_image(image_path)
    try:
        record = analyzer.analyze_image(path)
    except LLMUnavailableError:
        return f"이미지 분석 실패: {UNAVAILABLE_MESSAGE}", {"type": "vision", "error": UNAVAILABLE_MESSAGE}
    text = analyzer.format_for_llm(record)
    if question:
        text += f"\n사용자 질문: {question}"
    return text, {"type": "vision", **record}


@tool(response_format="content_and_artifact")
def write_farm_diary(date: str, notes: str):
    """영농일지를 정해진 양식으로 작성해 outputs/diary/YYYY-MM-DD.md로 저장한다.
    메모의 '온도 16', '습도 90%', 'CO2 900ppm' 값과 같은 날짜의 이미지 분석 결과를 반영한다.

    Args:
        date: 일지 날짜 YYYY-MM-DD (언급이 없으면 오늘 날짜)
        notes: 사용자가 말한 작업 내용·관찰 메모
    """
    try:
        day = date_cls.fromisoformat(date).isoformat()
    except ValueError:
        day = date_cls.today().isoformat()
    env = writer.parse_env_from_text(notes)
    analyses = [a for a in analyzer.list_cached_analyses() if a.get("analyzed_at", "").startswith(day)]
    md = writer.build_diary(day, env["temperature"], env["humidity"], env["co2"], notes, analyses)
    path = writer.save_diary(day, md)
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return f"영농일지 저장 완료: {rel}\n\n{md}", {"type": "diary", "path": str(path), "markdown": md}


@tool(response_format="content_and_artifact")
def get_mushroom_price(period: str = "1m"):
    """느타리버섯 도매·소매 가격 데이터를 조회해 기간 요약(최근가·평균·최저·최고·등락률)을 반환한다.

    Args:
        period: 조회 기간. 1w | 1m | 3m | 6m | 1y | all 중 하나 (기본 1m)
    """
    period = period if period in PERIODS else "1m"
    res = loaders.load_price_data()
    summary = loaders.price_summary(res.df, period)
    label = "SAMPLE(합성값, 실측 아님)" if res.is_sample else res.source_label
    if summary.empty:
        return f"가격 데이터 없음 (출처: {label})", {"type": "price", "source": label, "rows": []}
    lines = [f"느타리버섯 가격 요약 · 기간 {period} · 출처 {label}"]
    for r in summary.to_dict("records"):
        lines.append(f"- {r['market']} ({r['start']}~{r['end']}, {r['unit']}): 최근 {r['latest']:,.0f}원, "
                     f"평균 {r['mean']:,.0f}원, 최저 {r['min']:,.0f}원, 최고 {r['max']:,.0f}원, 기간 등락 {r['change_pct']:+.2f}%")
    if res.is_sample:
        lines.append("※ 샘플 데이터이므로 실제 시세로 해석하면 안 됨.")
    return "\n".join(lines), {"type": "price", "source": label, "is_sample": res.is_sample,
                              "period": period, "rows": summary.to_dict("records")}


ALL_TOOLS = [rag_search, analyze_mushroom_image, write_farm_diary, get_mushroom_price]
