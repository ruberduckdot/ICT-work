"""환경변수 로딩.

비밀값과 모델명은 `.env` 또는 프로세스 환경변수에서만 읽는다.
값은 호출 시점에 읽으므로 테스트에서 monkeypatch로 전환할 수 있다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

# 경로
DATA_RAW = ROOT / "data" / "raw"
DATA_SAMPLE = ROOT / "data" / "sample"
VECTORSTORE_DIR = ROOT / "vectorstore"
OUTPUTS = ROOT / "outputs"
DIARY_DIR = OUTPUTS / "diary"
CACHE_DIR = OUTPUTS / "cache"
UPLOAD_DIR = OUTPUTS / "uploads"

# Chroma 컬렉션
MANUALS_COLLECTION = "manuals"
ANALYSIS_COLLECTION = "analysis_logs"

# Agent
AGENT_MAX_ITERATIONS = 6
LLM_MAX_RETRIES = 2

PROVIDERS = ("mock", "gemini", "ollama")
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_model: str
    vlm_model: str
    google_api_key: str
    ollama_base_url: str
    embedding_model: str
    rag_score_threshold: float
    kamis_api_key: str
    kamis_api_id: str

    @property
    def is_mock(self) -> bool:
        return self.llm_provider == "mock"


def get_settings() -> Settings:
    provider = _env("LLM_PROVIDER", "mock").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER는 {PROVIDERS} 중 하나여야 함: {provider!r}")
    try:
        threshold = float(_env("RAG_SCORE_THRESHOLD", "0.80"))
    except ValueError:
        threshold = 0.80
    llm_model = _env("LLM_MODEL")
    return Settings(
        llm_provider=provider,
        llm_model=llm_model,
        vlm_model=_env("VLM_MODEL") or llm_model,
        google_api_key=_env("GOOGLE_API_KEY"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        embedding_model=_env("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        rag_score_threshold=threshold,
        kamis_api_key=_env("KAMIS_API_KEY"),
        kamis_api_id=_env("KAMIS_API_ID"),
    )
