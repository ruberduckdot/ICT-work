"""Streamlit 진입점: 대시보드 / 이미지 분석 / AI 상담 / 영농일지."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import get_settings
from src.dashboard import charts
from src.data import loaders
from src.llm.factory import describe_provider

st.set_page_config(page_title="느타리버섯 스마트 농업 AI", page_icon="🍄", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def _load_price():
    return loaders.load_price_data()


@st.cache_data(ttl=600, show_spinner=False)
def _load_production():
    return loaders.load_production_data()


def source_caption(result: loaders.LoadResult) -> None:
    st.caption(f"데이터 출처: **{'SAMPLE (합성값, 실측 아님)' if result.is_sample else result.source_label}**")


def render_sidebar() -> None:
    info = describe_provider()
    st.sidebar.header("모델 설정")
    st.sidebar.markdown(f"- LLM_PROVIDER: `{info['provider']}`\n- LLM: `{info['llm_model']}`\n- VLM: `{info['vlm_model']}`")
    if info["provider"] == "mock":
        st.sidebar.warning("데모 모드: mock 모델은 실제 생성·이미지 분석을 하지 않고 규칙 기반 고정 응답을 반환함")
    st.sidebar.caption(f"Embedding: `{get_settings().embedding_model}`")


def render_dashboard() -> None:
    price_res, prod_res = _load_price(), _load_production()
    if price_res.is_sample or prod_res.is_sample:
        st.warning("🧪 **샘플 데이터(실측 아님)** — `data/raw/`에 실데이터를 넣으면 자동으로 대체됨")
    for err in price_res.errors + prod_res.errors:
        st.error(err)

    price, prod = price_res.df, prod_res.df
    if price.empty or prod.empty:
        st.info("표시할 데이터가 없음")
        return

    c1, c2, c3 = st.columns([2, 2, 1])
    dmin, dmax = price["date"].min().date(), price["date"].max().date()
    period = c1.date_input("기간", value=(max(dmin, dmax - pd.Timedelta(days=365)), dmax),
                           min_value=dmin, max_value=dmax, key="dash_period")
    regions_all = sorted(prod["region"].unique())
    regions = c2.multiselect("지역 (미선택 시 전체)", regions_all, default=[], key="dash_regions")
    freq = c3.radio("단위", ["일", "월"], horizontal=True, key="dash_freq")

    start, end = (period if isinstance(period, tuple) and len(period) == 2 else (dmin, dmax))
    p = price[(price["date"].dt.date >= start) & (price["date"].dt.date <= end)]
    pr = prod[prod["region"].isin(regions)] if regions else prod

    latest_year = int(pr["year"].max()) if not pr.empty else None
    whole = p[p["market"] == "도매"].sort_values("date")
    _, mom = loaders.month_over_month(p, "도매")
    top = (pr[pr["year"] == latest_year].groupby("region")["production_ton"].sum().idxmax()
           if latest_year else "-")
    k1, k2, k3 = st.columns(3)
    k1.metric("최근 도매가", f"{whole['price'].iloc[-1]:,.0f}원" if not whole.empty else "-",
              help=f"{whole['date'].iloc[-1].date() if not whole.empty else ''} 기준, {price['unit'].iloc[-1]}")
    k2.metric("전월 대비 (도매 월평균)", f"{mom:+.2f}%" if mom is not None else "-")
    k3.metric(f"최대 생산 지역 ({latest_year}년)", top)

    markets = sorted(p["market"].unique())
    st.plotly_chart(charts.price_line(p, "D" if freq == "일" else "M", markets), use_container_width=True)
    source_caption(price_res)

    col_a, col_b = st.columns(2)
    with col_a:
        years = sorted(pr["year"].unique())
        year = st.selectbox("생산량 연도", years, index=len(years) - 1, key="dash_year")
        st.plotly_chart(charts.region_bar(pr, int(year)), use_container_width=True)
        source_caption(prod_res)
    with col_b:
        st.plotly_chart(charts.production_yoy(pr), use_container_width=True)
        source_caption(prod_res)
    st.plotly_chart(charts.seasonality_heatmap(price, "도매"), use_container_width=True)
    source_caption(price_res)

    with st.expander("데이터 표 보기"):
        st.dataframe(p.tail(200), use_container_width=True)
        st.dataframe(pr, use_container_width=True)


def main() -> None:
    st.title("🍄 느타리버섯 스마트 농업 AI 서비스")
    render_sidebar()
    tabs = st.tabs(["📊 대시보드", "🔬 이미지 분석", "💬 AI 상담", "📝 영농일지"])
    with tabs[0]:
        render_dashboard()
    with tabs[1]:
        st.info("이미지 분석 탭: 구현 예정")
    with tabs[2]:
        st.info("AI 상담 탭: 구현 예정")
    with tabs[3]:
        st.info("영농일지 탭: 구현 예정")


main()
