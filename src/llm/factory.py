"""LLM·VLM 공급자 생성. 공급자 객체는 이 모듈에서만 만든다.

Agent·Vision·Diary 모듈은 `get_chat_model()`, `get_vision_model()`,
`invoke_with_retry()`만 사용한다. 모델명은 환경변수(LLM_MODEL, VLM_MODEL)에서만 읽는다.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel

from src.config import LLM_MAX_RETRIES, Settings, get_settings
from src.llm.mock import MockChatModel

log = logging.getLogger(__name__)
T = TypeVar("T")

UNAVAILABLE_MESSAGE = "API 한도 초과 또는 모델 서버 미연결"


class LLMConfigError(RuntimeError):
    """공급자 설정 누락(모델명·키)."""


class LLMUnavailableError(RuntimeError):
    """재시도 후에도 429 또는 연결 오류가 계속됨."""


def _require_model(name: str | None, env_name: str, provider: str) -> str:
    if not name:
        raise LLMConfigError(f"LLM_PROVIDER={provider} 사용 시 환경변수 {env_name}를 지정해야 함")
    return name


def _build(provider: str, model: str | None, env_name: str, settings: Settings, mock_mode: str,
           temperature: float) -> BaseChatModel:
    if provider == "mock":
        return MockChatModel(mode=mock_mode)
    if provider == "gemini":
        if not settings.google_api_key:
            raise LLMConfigError("LLM_PROVIDER=gemini 사용 시 GOOGLE_API_KEY를 지정해야 함")
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=_require_model(model, env_name, provider),
            google_api_key=settings.google_api_key,
            temperature=temperature,
            max_retries=0,  # 재시도는 invoke_with_retry에서 일괄 처리
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=_require_model(model, env_name, provider),
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )
    raise LLMConfigError(f"지원하지 않는 공급자: {provider}")


def get_chat_model(settings: Settings | None = None, temperature: float = 0.2) -> BaseChatModel:
    """Agent·영농일지용 Chat 모델."""
    s = settings or get_settings()
    return _build(s.llm_provider, s.llm_model, "LLM_MODEL", s, "agent", temperature)


def get_text_model(settings: Settings | None = None, temperature: float = 0.3) -> BaseChatModel:
    """Tool 없이 텍스트만 생성하는 용도(영농일지 등). mock은 text 모드."""
    s = settings or get_settings()
    return _build(s.llm_provider, s.llm_model, "LLM_MODEL", s, "text", temperature)


def get_vision_model(settings: Settings | None = None) -> BaseChatModel:
    """이미지 분석용 VLM. VLM_MODEL 미지정 시 LLM_MODEL을 사용."""
    s = settings or get_settings()
    return _build(s.llm_provider, s.vlm_model, "VLM_MODEL", s, "vision", 0.0)


def describe_provider(settings: Settings | None = None) -> dict[str, str]:
    s = settings or get_settings()
    if s.is_mock:
        return {"provider": "mock", "llm_model": "MockChatModel", "vlm_model": "MockChatModel(vision)"}
    return {
        "provider": s.llm_provider,
        "llm_model": s.llm_model or "(LLM_MODEL 미지정)",
        "vlm_model": s.vlm_model or "(VLM_MODEL 미지정)",
    }


def is_retryable(exc: BaseException) -> bool:
    """429(Rate limit) 또는 연결 오류 여부."""
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return True
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__
    text = str(exc)
    markers = ("429", "ResourceExhausted", "RESOURCE_EXHAUSTED", "rate limit", "Rate limit",
               "Connection refused", "ConnectError", "Failed to connect", "connection error")
    return name in {"ConnectError", "ConnectTimeout", "ResourceExhausted", "ReadTimeout"} or any(
        m in text for m in markers
    )


def invoke_with_retry(fn: Callable[[], T], retries: int = LLM_MAX_RETRIES, base_delay: float = 1.0,
                      sleep: Callable[[float], Any] = time.sleep) -> T:
    """지수 백오프(1s, 2s, ...)로 최대 `retries`회 재시도. 실패 시 LLMUnavailableError."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 공급자별 예외 타입이 다름
            if not is_retryable(exc):
                raise
            if attempt >= retries:
                log.warning("LLM 호출 실패(재시도 소진): %s", type(exc).__name__)
                raise LLMUnavailableError(UNAVAILABLE_MESSAGE) from exc
            delay = base_delay * (2 ** attempt)
            log.info("LLM 호출 재시도 %d/%d (%.1fs 후): %s", attempt + 1, retries, delay, type(exc).__name__)
            sleep(delay)
            attempt += 1
