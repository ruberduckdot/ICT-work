"""VLM 기반 느타리버섯 이미지 분석 (Zero-shot, 학습 없음).

- base64 이미지를 VLM에 전달하고 Pydantic 스키마(JSON)로 구조화 출력을 받는다.
- 파싱 실패 시 1회 재요청, 그래도 실패하면 '판단불가' 객체를 반환한다(캐시하지 않음).
- 결과는 이미지 SHA-256(+공급자·모델) 키로 outputs/cache/에 캐시하고,
  Chroma `analysis_logs` 컬렉션에 메타데이터와 함께 저장한다.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from src.config import ANALYSIS_COLLECTION, CACHE_DIR, get_settings
from src.llm.factory import describe_provider, get_vision_model, invoke_with_retry

log = logging.getLogger(__name__)

GrowthStage = Literal["균사생장", "원기형성", "자실체생장", "수확적기", "과숙", "판단불가"]
Disease = Literal["정상", "푸른곰팡이병", "세균성갈색무늬병", "버섯파리 피해", "기타", "판단불가"]


class MushroomAnalysis(BaseModel):
    growth_stage: GrowthStage = Field(description="생육 단계")
    disease_suspected: Disease = Field(description="의심 병해충")
    confidence: float = Field(ge=0.0, le=1.0, description="판단 신뢰도 0~1")
    visual_evidence: list[str] = Field(default_factory=list, description="이미지에서 관찰된 근거")
    recommended_actions: list[str] = Field(default_factory=list, description="권장 조치")
    summary_ko: str = Field(description="한국어 자연어 요약")


UNKNOWN = MushroomAnalysis(
    growth_stage="판단불가", disease_suspected="판단불가", confidence=0.0,
    visual_evidence=[], recommended_actions=["이미지를 다시 촬영하거나 실모델로 재분석"],
    summary_ko="모델 응답을 구조화하지 못해 판단불가로 처리함.",
)

SYSTEM_PROMPT = f"""당신은 느타리버섯 재배 이미지를 판독하는 보조 분석가다.
규칙:
1. 이미지에서 관찰되는 근거만 기술한다. 보이지 않는 내용을 추측하지 않는다.
2. 불확실하면 growth_stage 또는 disease_suspected에 "판단불가"를 쓰고 confidence를 0.3 이하로 낮게 반환한다.
3. 느타리버섯 재배 이미지가 아니면 둘 다 "판단불가", confidence 0.1 이하로 반환한다.
4. 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력한다. 설명 문장, 코드블록 표시는 쓰지 않는다.
허용값:
- growth_stage: 균사생장 | 원기형성 | 자실체생장 | 수확적기 | 과숙 | 판단불가
- disease_suspected: 정상 | 푸른곰팡이병 | 세균성갈색무늬병 | 버섯파리 피해 | 기타 | 판단불가
JSON 스키마:
{json.dumps(MushroomAnalysis.model_json_schema(), ensure_ascii=False)}"""

USER_PROMPT = "이 느타리버섯 재배 이미지의 생육 단계와 병해충 의심 여부를 분석해 JSON으로만 답하라."
RETRY_PROMPT = "직전 응답이 스키마에 맞는 JSON이 아님. 설명 없이 스키마에 맞는 JSON 객체 하나만 다시 출력하라."


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def encode_image(path: Path, max_side: int = 1024) -> str:
    """긴 변을 max_side 이하로 줄여 JPEG base64 data URL로 반환 (전송량 절감)."""
    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse_analysis(text: str) -> MushroomAnalysis | None:
    if not isinstance(text, str):
        text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in text)
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return MushroomAnalysis.model_validate(json.loads(text[start:end + 1]))
    except (json.JSONDecodeError, ValidationError):
        return None


def _cache_key(sha: str) -> str:
    info = describe_provider()
    model = re.sub(r"[^\w.-]", "_", info["vlm_model"])
    return f"{sha}__{info['provider']}__{model}"


def call_vlm(image_path: Path, model=None) -> tuple[MushroomAnalysis, str]:
    """(분석결과, parse_status: ok | retried | failed)"""
    model = model or get_vision_model()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=[
            {"type": "text", "text": USER_PROMPT},
            {"type": "image_url", "image_url": {"url": encode_image(image_path)}},
        ]),
    ]
    first = invoke_with_retry(lambda: model.invoke(messages))
    parsed = parse_analysis(first.content)
    if parsed:
        return parsed, "ok"
    log.info("Vision 구조화 출력 파싱 실패 → 1회 재요청")
    retry_msgs = messages + [AIMessage(content=first.content), HumanMessage(content=RETRY_PROMPT)]
    second = invoke_with_retry(lambda: model.invoke(retry_msgs))
    parsed = parse_analysis(second.content)
    if parsed:
        return parsed, "retried"
    return UNKNOWN.model_copy(), "failed"


def log_to_vectorstore(record: dict, persist_dir: Path | None = None) -> None:
    """분석 결과를 `analysis_logs` 컬렉션에 upsert (같은 키는 덮어씀)."""
    from src.rag.embeddings import get_embeddings
    from src.rag.ingest import collection_backend, get_store, reset_analysis_logs

    store = get_store(ANALYSIS_COLLECTION, persist_dir)
    _, backend, _ = get_embeddings()
    if store._collection.count() and collection_backend(store) != backend:
        reset_analysis_logs(persist_dir)
        store = get_store(ANALYSIS_COLLECTION, persist_dir)
    r = record["result"]
    text = (f"[이미지 분석 기록] 파일 {record['file_name']} / 분석시각 {record['analyzed_at']} / "
            f"생육단계 {r['growth_stage']} / 병해충 {r['disease_suspected']} / 신뢰도 {r['confidence']:.2f}\n"
            f"관찰 근거: {'; '.join(r['visual_evidence'])}\n권장 조치: {'; '.join(r['recommended_actions'])}\n"
            f"요약: {r['summary_ko']}")
    meta = {"file_name": record["file_name"], "analyzed_at": record["analyzed_at"],
            "growth_stage": r["growth_stage"], "disease_suspected": r["disease_suspected"],
            "confidence": float(r["confidence"]), "sha256": record["sha256"],
            "provider": record["provider"], "model": record["model"]}
    store.add_documents([Document(page_content=text, metadata=meta)], ids=[record["cache_key"]])


def analyze_image(image_path: str | Path, *, use_cache: bool = True, cache_dir: Path | None = None,
                  persist_dir: Path | None = None, log_vector: bool = True, model=None) -> dict:
    """이미지 분석 레코드(dict) 반환. 키: result, cached, sha256, file_name, analyzed_at, provider, model,
    parse_status, cache_key"""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"이미지 파일 없음: {path}")
    cache_dir = cache_dir or CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    sha = sha256_of(path)
    key = _cache_key(sha)
    cache_file = cache_dir / f"{key}.json"
    if use_cache and cache_file.exists():
        record = json.loads(cache_file.read_text(encoding="utf-8"))
        record["cached"] = True
        return record

    analysis, status = call_vlm(path, model)
    info = describe_provider()
    record = {
        "result": analysis.model_dump(),
        "cached": False,
        "sha256": sha,
        "cache_key": key,
        "file_name": path.name,
        "image_path": str(path),
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "provider": info["provider"],
        "model": info["vlm_model"],
        "parse_status": status,
        "is_mock": get_settings().is_mock,
    }
    if status != "failed":
        cache_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if log_vector:
            try:
                log_to_vectorstore(record, persist_dir)
            except Exception as exc:  # noqa: BLE001 - 벡터 저장 실패가 분석 결과 반환을 막지 않게 함
                log.warning("analysis_logs 저장 실패: %s", exc)
                record["vector_log_error"] = str(exc)
    return record


def list_cached_analyses(cache_dir: Path | None = None, limit: int = 50) -> list[dict]:
    cache_dir = cache_dir or CACHE_DIR
    if not cache_dir.exists():
        return []
    records = []
    for f in cache_dir.glob("*.json"):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    records.sort(key=lambda r: r.get("analyzed_at", ""), reverse=True)
    return records[:limit]


def format_for_llm(record: dict) -> str:
    r = record["result"]
    tag = " (mock: 실제 분석 아님)" if record.get("is_mock") else ""
    return (f"이미지 분석 결과{tag} — 파일 {record['file_name']}, 캐시 {'사용' if record['cached'] else '미사용'}\n"
            f"- 생육 단계: {r['growth_stage']}\n- 병해충 의심: {r['disease_suspected']}\n"
            f"- 신뢰도: {r['confidence']:.2f}\n- 관찰 근거: {'; '.join(r['visual_evidence']) or '없음'}\n"
            f"- 권장 조치: {'; '.join(r['recommended_actions']) or '없음'}\n- 요약: {r['summary_ko']}")
