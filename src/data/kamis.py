"""KAMIS Open API 클라이언트 (선택 기능).

KAMIS_API_KEY와 KAMIS_API_ID가 있을 때만 호출한다. 키가 없거나 호출에 실패하면
None 또는 오류가 담긴 빈 LoadResult를 반환하고, 로더가 파일·샘플로 대체한다.

[미확인] 아래 엔드포인트·액션·파라미터명·응답 필드는 공개 문서 기준 기억에 의존하며
이 개발 환경에서는 KAMIS 접속이 차단되어 검증하지 못했다.
사용 전 KAMIS Open API 안내(https://www.kamis.or.kr → 오픈API) 문서로 확인할 것.
느타리버섯 품목·품종 코드는 추측해 넣지 않고 환경변수로 받는다.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import pandas as pd
import requests

from src.config import get_settings

log = logging.getLogger(__name__)

KAMIS_URL = "https://www.kamis.or.kr/service/price/xml.do"  # [미확인] 경로
ACTION = "periodProductList"  # [미확인] 기간별 품목 가격 액션명
MARKET_CODES = {"소매": "01", "도매": "02"}  # [미확인] p_productclscode 값


def _params(cls_code: str, start: date, end: date) -> dict[str, str]:
    s = get_settings()
    return {
        "action": ACTION,
        "p_productclscode": cls_code,
        "p_startday": start.isoformat(),
        "p_endday": end.isoformat(),
        # [미확인] 품목분류·품목·품종 코드. KAMIS 코드표에서 확인 후 .env에 지정
        "p_itemcategorycode": os.getenv("KAMIS_CATEGORY_CODE", ""),
        "p_itemcode": os.getenv("KAMIS_ITEM_CODE", ""),
        "p_kindcode": os.getenv("KAMIS_KIND_CODE", ""),
        "p_productrankcode": os.getenv("KAMIS_RANK_CODE", ""),
        "p_convert_kg_yn": "Y",
        "p_cert_key": s.kamis_api_key,
        "p_cert_id": s.kamis_api_id,
        "p_returntype": "json",
    }


def _parse(payload: dict, market: str) -> pd.DataFrame:
    # [미확인] 응답 구조: {"data": {"item": [{"yyyy","regday","price","itemname","kindname",...}]}}
    items = (payload.get("data") or {}).get("item") or []
    rows = []
    for it in items:
        if str(it.get("countyname", "")) not in ("", "평균"):
            continue
        try:
            d = pd.to_datetime(f"{it['yyyy']}-{it['regday'].replace('/', '-')}")
            price = float(str(it["price"]).replace(",", ""))
        except (KeyError, ValueError, AttributeError):
            continue
        rows.append({"date": d, "item": it.get("itemname", "느타리버섯"), "kind": it.get("kindname", ""),
                     "market": market, "unit": "원/kg(p_convert_kg_yn=Y)", "price": price, "is_sample": False})
    return pd.DataFrame(rows)


def fetch_price_if_configured(days: int = 365, timeout: float = 10.0):
    from src.data.loaders import PRICE_COLUMNS, LoadResult

    s = get_settings()
    if not (s.kamis_api_key and s.kamis_api_id):
        return None
    if not os.getenv("KAMIS_ITEM_CODE"):
        return LoadResult(pd.DataFrame(columns=PRICE_COLUMNS), False, "KAMIS API", [],
                          ["KAMIS_API_KEY는 있으나 KAMIS_ITEM_CODE(느타리버섯 품목코드)가 없어 API 조회를 건너뜀"])
    end = date.today()
    start = end - timedelta(days=days)
    frames, errors = [], []
    for market, code in MARKET_CODES.items():
        try:
            resp = requests.get(KAMIS_URL, params=_params(code, start, end), timeout=timeout)
            resp.raise_for_status()
            frames.append(_parse(resp.json(), market))
        except Exception as exc:  # noqa: BLE001 - 네트워크·파싱 오류 모두 대체 경로로
            errors.append(f"KAMIS API {market} 조회 실패: {type(exc).__name__}")
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    if df.empty and not errors:
        errors.append("KAMIS API 응답에 가격 데이터가 없음 (파라미터 확인 필요)")
    return LoadResult(df.reindex(columns=PRICE_COLUMNS), False, "실데이터(KAMIS Open API)", ["KAMIS API"], errors)
