"""가격·생산 통계 로딩.

우선순위
- 가격: KAMIS Open API(KAMIS_API_KEY 있을 때) → data/raw/price/*.xlsx|*.csv → 샘플
- 생산: data/raw/production/*.csv (KOSIS 다운로드, wide→long) → 샘플

반환값 `LoadResult`는 출처 표기(`source_label`)와 샘플 여부를 함께 담는다.
표준 컬럼
- 가격: date(datetime), item, kind, market(도매/소매), unit, price(float), is_sample
- 생산: year(int), region, item, production_ton(float), is_sample
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.config import DATA_RAW, DATA_SAMPLE

log = logging.getLogger(__name__)

PRICE_COLUMNS = ["date", "item", "kind", "market", "unit", "price", "is_sample"]
PRODUCTION_COLUMNS = ["year", "region", "item", "production_ton", "is_sample"]

# KAMIS 웹 다운로드 파일의 컬럼명은 화면·기간에 따라 다를 수 있어 후보를 나열함 [미확인: 실제 파일로 확인 필요]
PRICE_COLUMN_MAP: dict[str, list[str]] = {
    "date": ["date", "일자", "날짜", "조사일", "조사일자", "regday", "yyyy-mm-dd", "기준일"],
    "price": ["price", "가격", "평균가격", "평균가", "당일", "가격(원)", "price(원)", "dpr1"],
    "market": ["market", "구분", "도소매", "도소매구분", "시장구분", "유통단계"],
    "item": ["item", "품목", "품목명", "itemname", "item_name"],
    "kind": ["kind", "품종", "품종명", "kindname", "kind_name"],
    "unit": ["unit", "단위"],
}
PRICE_REQUIRED = ("date", "price")

REGION_CANDIDATES = ["region", "시도별", "시도", "지역", "지역별", "행정구역별", "시도명"]
ITEM_CANDIDATES = ["item", "품목별", "버섯류별", "버섯별", "작물별", "특용작물별", "품목"]
INDICATOR_CANDIDATES = ["항목", "항목별", "지표"]
AGGREGATE_REGIONS = {"전국", "계", "합계", "총계", "전체"}
YEAR_RE = re.compile(r"((?:19|20)\d{2})")


@dataclass
class LoadResult:
    df: pd.DataFrame
    is_sample: bool
    source_label: str
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 공통 유틸
def read_csv_auto(path: Path, **kwargs) -> pd.DataFrame:
    """utf-8(-sig) → cp949 → euc-kr 순서로 인코딩 자동 판별."""
    last_exc: Exception | None = None
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except UnicodeDecodeError as exc:
            last_exc = exc
    raise ValueError(f"{path.name}: 인코딩 판별 실패 ({last_exc})")


def _norm(col: object) -> str:
    return re.sub(r"\s+", "", str(col)).lower()


def _find_column(columns, candidates: list[str]) -> str | None:
    normed = {_norm(c): c for c in columns}
    for cand in candidates:
        if _norm(cand) in normed:
            return normed[_norm(cand)]
    for cand in candidates:  # 부분 일치 (예: "평균가격(원)")
        for n, original in normed.items():
            if _norm(cand) in n:
                return original
    return None


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"-": None, "": None, "nan": None}),
        errors="coerce",
    )


def _list_files(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pat in patterns:
        files.extend(sorted(folder.glob(pat)))
    return [f for f in files if not f.name.startswith(("~$", "."))]


# ---------------------------------------------------------------- 가격
def normalize_price_frame(raw: pd.DataFrame, file_name: str = "") -> tuple[pd.DataFrame | None, str | None]:
    """원본 가격표를 표준 컬럼으로 변환. 실패 시 (None, 오류메시지)."""
    mapping = {std: _find_column(raw.columns, cands) for std, cands in PRICE_COLUMN_MAP.items()}
    missing = [k for k in PRICE_REQUIRED if mapping[k] is None]
    if missing:
        need = ", ".join(f"{k}({'/'.join(PRICE_COLUMN_MAP[k][:4])} …)" for k in missing)
        return None, (
            f"{file_name}: 필수 컬럼 매핑 실패 → 필요 컬럼: {need} / "
            f"파일 컬럼: {', '.join(map(str, raw.columns[:12]))}"
        )
    df = pd.DataFrame()
    df["date"] = pd.to_datetime(raw[mapping["date"]].astype(str).str.replace(r"[./]", "-", regex=True), errors="coerce")
    df["price"] = _to_number(raw[mapping["price"]])
    if mapping["market"]:
        market = raw[mapping["market"]].astype(str)
        df["market"] = market.where(~market.str.contains("도매"), "도매").where(~market.str.contains("소매"), "소매")
    else:
        df["market"] = "소매" if "소매" in file_name else ("도매" if "도매" in file_name else "미지정")
    df["item"] = raw[mapping["item"]].astype(str) if mapping["item"] else "느타리버섯"
    df["kind"] = raw[mapping["kind"]].astype(str) if mapping["kind"] else df["item"]
    df["unit"] = raw[mapping["unit"]].astype(str) if mapping["unit"] else "[미확인 단위]"
    df["is_sample"] = False
    df = df.dropna(subset=["date", "price"])
    if df.empty:
        return None, f"{file_name}: 날짜·가격 값이 비어 있거나 형식을 해석하지 못함"
    if df["item"].str.contains("느타리").any():
        df = df[df["item"].str.contains("느타리") | df["kind"].str.contains("느타리")]
    return df[PRICE_COLUMNS].sort_values("date").reset_index(drop=True), None


def load_price_files(folder: Path | None = None) -> LoadResult | None:
    folder = folder or DATA_RAW / "price"
    files = _list_files(folder, ("*.csv", "*.xlsx", "*.xls"))
    if not files:
        return None
    frames, errors, used = [], [], []
    for f in files:
        try:
            raw = read_csv_auto(f) if f.suffix.lower() == ".csv" else pd.read_excel(f)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{f.name}: 읽기 실패 ({exc})")
            continue
        df, err = normalize_price_frame(raw, f.name)
        if err:
            errors.append(err)
        else:
            frames.append(df)
            used.append(f.name)
    if not frames:
        return LoadResult(pd.DataFrame(columns=PRICE_COLUMNS), False, "실데이터 매핑 실패", [], errors)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["date", "market", "kind"]).sort_values("date")
    return LoadResult(df.reset_index(drop=True), False, f"실데이터({', '.join(used)})", used, errors)


def load_price_sample() -> LoadResult:
    from src.data.make_sample import PRICE_FILE, make_price_sample

    if PRICE_FILE.exists():
        df = read_csv_auto(PRICE_FILE, parse_dates=["date"])
    else:
        df = make_price_sample()
    return LoadResult(df[PRICE_COLUMNS], True, "SAMPLE", [PRICE_FILE.name])


def load_price_data(use_api: bool = True) -> LoadResult:
    errors: list[str] = []
    if use_api:
        from src.data import kamis

        api_result = kamis.fetch_price_if_configured()
        if api_result is not None:
            if api_result.errors:
                errors.extend(api_result.errors)
            if not api_result.df.empty:
                return api_result
    file_result = load_price_files()
    if file_result is not None:
        errors.extend(file_result.errors)
        if not file_result.df.empty:
            file_result.errors = errors
            return file_result
    sample = load_price_sample()
    sample.errors = errors
    return sample


# ---------------------------------------------------------------- 생산
def normalize_production_frame(raw: pd.DataFrame, file_name: str = "") -> tuple[pd.DataFrame | None, str | None]:
    """KOSIS wide(연도 컬럼) 또는 long 형식을 표준 long 형식으로 변환."""
    raw = raw.copy()
    raw.columns = [str(c).strip() for c in raw.columns]
    region_col = _find_column(raw.columns, REGION_CANDIDATES)
    if region_col is None:
        return None, (f"{file_name}: 지역 컬럼을 찾지 못함 → 필요 컬럼: {'/'.join(REGION_CANDIDATES[:5])} / "
                      f"파일 컬럼: {', '.join(raw.columns[:12])}")
    item_col = _find_column([c for c in raw.columns if c != region_col], ITEM_CANDIDATES)
    ind_col = _find_column([c for c in raw.columns if c not in (region_col, item_col)], INDICATOR_CANDIDATES)

    year_cols = [c for c in raw.columns if YEAR_RE.search(c) and c not in (region_col, item_col, ind_col)]
    if year_cols:  # wide → long
        # KOSIS는 첫 데이터 행에 단위 설명이 들어가는 경우가 있어 숫자가 아닌 행은 이후 제거됨
        id_cols = [c for c in (region_col, item_col, ind_col) if c]
        long = raw.melt(id_vars=id_cols, value_vars=year_cols, var_name="year_raw", value_name="value")
        long["year"] = long["year_raw"].str.extract(YEAR_RE, expand=False)
    else:
        year_col = _find_column(raw.columns, ["year", "연도", "시점", "년도"])
        value_col = _find_column(raw.columns, ["production_ton", "생산량", "value", "값", "데이터"])
        if not year_col or not value_col:
            return None, (f"{file_name}: 연도 컬럼(예: 2019, 2020 …) 또는 year/생산량 컬럼이 필요함 / "
                          f"파일 컬럼: {', '.join(raw.columns[:12])}")
        long = raw.rename(columns={year_col: "year_raw", value_col: "value"})
        long["year"] = long["year_raw"].astype(str).str.extract(YEAR_RE, expand=False)

    if ind_col:
        is_prod = long[ind_col].astype(str).str.contains("생산")
        if is_prod.any():
            long = long[is_prod]
    out = pd.DataFrame({
        "year": pd.to_numeric(long["year"], errors="coerce"),
        "region": long[region_col].astype(str).str.strip(),
        "item": long[item_col].astype(str).str.strip() if item_col else "버섯류(품목 미구분)",
        "production_ton": _to_number(long["value"]),
    })
    if item_col and out["item"].str.contains("느타리").any():
        out = out[out["item"].str.contains("느타리")]
    out = out[~out["region"].isin(AGGREGATE_REGIONS)].dropna(subset=["year", "production_ton"])
    if out.empty:
        return None, f"{file_name}: 변환 후 유효한 생산량 값이 없음"
    out["year"] = out["year"].astype(int)
    out["is_sample"] = False
    out = out.groupby(["year", "region", "item"], as_index=False)["production_ton"].sum()
    out["is_sample"] = False
    return out[PRODUCTION_COLUMNS].sort_values(["year", "region"]).reset_index(drop=True), None


def load_production_data(folder: Path | None = None) -> LoadResult:
    folder = folder or DATA_RAW / "production"
    files = _list_files(folder, ("*.csv", "*.xlsx"))
    errors, frames, used = [], [], []
    for f in files:
        try:
            raw = read_csv_auto(f) if f.suffix.lower() == ".csv" else pd.read_excel(f)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{f.name}: 읽기 실패 ({exc})")
            continue
        df, err = normalize_production_frame(raw, f.name)
        if err:
            errors.append(err)
        else:
            frames.append(df)
            used.append(f.name)
    if frames:
        df = pd.concat(frames, ignore_index=True).drop_duplicates(["year", "region", "item"])
        return LoadResult(df.reset_index(drop=True), False, f"실데이터({', '.join(used)})", used, errors)

    from src.data.make_sample import PRODUCTION_FILE, make_production_sample

    df = read_csv_auto(PRODUCTION_FILE) if PRODUCTION_FILE.exists() else make_production_sample()
    return LoadResult(df[PRODUCTION_COLUMNS], True, "SAMPLE", [PRODUCTION_FILE.name], errors)


# ---------------------------------------------------------------- 조회 헬퍼 (Tool·KPI 공용)
PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365}


def filter_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty or period == "all" or period not in PERIOD_DAYS:
        return df
    end = df["date"].max()
    return df[df["date"] > end - pd.Timedelta(days=PERIOD_DAYS[period])]


def price_summary(df: pd.DataFrame, period: str = "1m") -> pd.DataFrame:
    """시장(도매/소매)별 기간 요약: 최근가, 평균, 최저, 최고, 기간 등락률."""
    sub = filter_period(df, period)
    rows = []
    for market, g in sub.sort_values("date").groupby("market"):
        first, last = g["price"].iloc[0], g["price"].iloc[-1]
        rows.append({
            "market": market,
            "start": g["date"].min().date().isoformat(),
            "end": g["date"].max().date().isoformat(),
            "latest": float(last),
            "mean": round(float(g["price"].mean()), 1),
            "min": float(g["price"].min()),
            "max": float(g["price"].max()),
            "change_pct": round((last - first) / first * 100, 2) if first else None,
            "unit": g["unit"].iloc[-1],
        })
    return pd.DataFrame(rows)


def month_over_month(df: pd.DataFrame, market: str = "도매") -> tuple[float | None, float | None]:
    """(최근 월 평균, 전월 대비 %)."""
    sub = df[df["market"] == market]
    if sub.empty:
        return None, None
    monthly = sub.set_index("date")["price"].resample("MS").mean().dropna()
    if len(monthly) < 2:
        return (float(monthly.iloc[-1]) if len(monthly) else None), None
    last, prev = monthly.iloc[-1], monthly.iloc[-2]
    return float(last), round(float((last - prev) / prev * 100), 2)
