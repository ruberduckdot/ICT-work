"""샘플 데이터 생성기.

여기서 만드는 가격·생산량은 **합성값(실측 아님)** 이며 모든 행에 `is_sample=True`를 넣는다.
실데이터가 `data/raw/`에 있으면 로더가 실데이터를 우선 사용한다.

실행: python -m src.data.make_sample
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import DATA_SAMPLE

PRICE_FILE = DATA_SAMPLE / "price_sample.csv"
PRODUCTION_FILE = DATA_SAMPLE / "production_sample.csv"
IMAGE_DIR = DATA_SAMPLE / "images"

# 시도 17개 (행정구역 명칭)
REGIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
    "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도",
]

SAMPLE_START = "2023-10-01"
SAMPLE_END = "2026-09-30"


def make_price_sample(seed: int = 42) -> pd.DataFrame:
    """일별 도매·소매 가격 합성값(원/kg). 실측 아님."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(SAMPLE_START, SAMPLE_END)
    t = np.arange(len(days))
    season = np.array([math.sin(2 * math.pi * (d.dayofyear / 365.0)) for d in days])
    wholesale = 5200 + 3.0 * t / 30 + 600 * season + rng.normal(0, 180, len(days))
    retail = wholesale * 1.65 + rng.normal(0, 250, len(days))
    rows = []
    for market, values in (("도매", wholesale), ("소매", retail)):
        rows.append(pd.DataFrame({
            "date": days,
            "item": "느타리버섯",
            "kind": "느타리버섯",
            "market": market,
            "unit": "원/kg(샘플 가정 단위)",
            "price": np.round(values, -1).astype(int),
        }))
    df = pd.concat(rows, ignore_index=True)
    df["is_sample"] = True
    return df


def make_production_sample(seed: int = 7) -> pd.DataFrame:
    """시도별 연간 생산량 합성값(톤). 실측 아님."""
    rng = np.random.default_rng(seed)
    weights = rng.gamma(shape=1.2, scale=1.0, size=len(REGIONS))
    # 합성값이 도(道) 지역 위주가 되도록 특별·광역시 가중치를 낮춤 (실제 분포를 재현한 것이 아님)
    for i, r in enumerate(REGIONS):
        if r.endswith(("특별시", "광역시", "특별자치시")):
            weights[i] *= 0.15
    weights /= weights.sum()
    rows = []
    total = 45000.0
    for year in range(2019, 2025):
        total *= 1 + rng.normal(-0.01, 0.04)
        for region, w in zip(REGIONS, weights):
            value = total * w * (1 + rng.normal(0, 0.08))
            rows.append({"year": year, "region": region, "item": "느타리버섯", "production_ton": round(max(value, 0), 1)})
    df = pd.DataFrame(rows)
    df["is_sample"] = True
    return df


def make_dummy_images(out_dir: Path = IMAGE_DIR) -> list[Path]:
    """mock 테스트 전용 단색 더미 이미지. 실제 버섯 사진이 아님."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [("mock_test_dummy_gray.png", (180, 180, 170)), ("mock_test_dummy_green.png", (60, 140, 70))]
    paths = []
    for name, color in specs:
        p = out_dir / name
        Image.new("RGB", (64, 64), color).save(p)
        paths.append(p)
    return paths


def main() -> None:
    DATA_SAMPLE.mkdir(parents=True, exist_ok=True)
    make_price_sample().to_csv(PRICE_FILE, index=False, encoding="utf-8-sig")
    make_production_sample().to_csv(PRODUCTION_FILE, index=False, encoding="utf-8-sig")
    imgs = make_dummy_images()
    print(f"[SAMPLE] {PRICE_FILE.relative_to(DATA_SAMPLE.parent.parent)}")
    print(f"[SAMPLE] {PRODUCTION_FILE.relative_to(DATA_SAMPLE.parent.parent)}")
    for p in imgs:
        print(f"[SAMPLE] {p.relative_to(DATA_SAMPLE.parent.parent)}")


if __name__ == "__main__":
    main()
