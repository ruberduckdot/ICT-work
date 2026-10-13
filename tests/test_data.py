import pandas as pd
import plotly.graph_objects as go

from src.dashboard import charts
from src.data import loaders


def test_sample_fallback_when_raw_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, "DATA_RAW", tmp_path)
    price = loaders.load_price_data()
    prod = loaders.load_production_data(tmp_path / "production")
    assert price.is_sample and price.source_label == "SAMPLE"
    assert prod.is_sample and prod.source_label == "SAMPLE"
    assert price.df["is_sample"].all() and prod.df["is_sample"].all()
    assert set(price.df["market"]) == {"도매", "소매"}
    assert list(price.df.columns) == loaders.PRICE_COLUMNS


def test_price_file_column_mapping(tmp_path):
    raw = pd.DataFrame({"일자": ["2025.01.02", "2025.01.03"], "품목명": ["느타리버섯"] * 2,
                        "구분": ["도매", "소매"], "평균가격(원)": ["5,120", "8,900"], "단위": ["1kg"] * 2})
    raw.to_csv(tmp_path / "kamis.csv", index=False, encoding="cp949")
    res = loaders.load_price_files(tmp_path)
    assert not res.is_sample and res.source_label == "실데이터(kamis.csv)"
    assert res.df["price"].tolist() == [5120.0, 8900.0]
    assert res.df["market"].tolist() == ["도매", "소매"]


def test_price_file_mapping_failure_reports_required_columns(tmp_path):
    pd.DataFrame({"foo": [1], "bar": [2]}).to_csv(tmp_path / "bad.csv", index=False)
    res = loaders.load_price_files(tmp_path)
    assert res.df.empty and res.errors
    assert "필요 컬럼" in res.errors[0] and "date" in res.errors[0]


def test_kosis_wide_to_long_cp949(tmp_path):
    raw = pd.DataFrame({
        "시도별": ["전국", "경기도", "경상북도", "경기도"],
        "버섯류별": ["느타리버섯", "느타리버섯", "느타리버섯", "표고버섯"],
        "2022": ["100", "60", "40", "9"], "2023 년": ["110", "-", "50", "8"],
    })
    raw.to_csv(tmp_path / "kosis.csv", index=False, encoding="cp949")
    res = loaders.load_production_data(tmp_path)
    df = res.df
    assert not res.is_sample
    assert set(df["region"]) == {"경기도", "경상북도"}  # 전국 제외, 표고 제외
    assert set(df["year"]) == {2022, 2023}
    assert df.query("region=='경상북도' and year==2023")["production_ton"].item() == 50.0
    assert df.query("region=='경기도'").shape[0] == 1  # '-' 값은 제거


def test_price_summary_and_mom():
    df = loaders.load_price_sample().df
    summ = loaders.price_summary(df, "1m")
    assert set(summ["market"]) == {"도매", "소매"}
    latest, mom = loaders.month_over_month(df)
    assert latest > 0 and mom is not None


def test_charts_build():
    price = loaders.load_price_sample().df
    prod = loaders.load_production_data(loaders.DATA_RAW / "__none__").df
    figs = [charts.price_line(price, "D"), charts.price_line(price, "M", ["도매"]),
            charts.region_bar(prod), charts.production_yoy(prod), charts.seasonality_heatmap(price)]
    assert all(isinstance(f, go.Figure) and len(f.data) >= 1 for f in figs)
