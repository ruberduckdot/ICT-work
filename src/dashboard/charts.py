"""Plotly 차트 함수. 각 함수는 표준 컬럼 DataFrame을 받아 Figure를 반환한다.

색상: 범주형은 고정 순서(도매=slot1 blue, 소매=slot2 orange), 크기는 단일 hue(blue) 순차 램프,
증감률은 blue↔red 발산 + 회색 중립점. 이중 축은 쓰지 않는다.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

MARKET_COLORS = {"도매": "#2a78d6", "소매": "#eb6834", "미지정": "#1baf7a"}
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0.0, "#e34948"], [0.5, "#f0efec"], [1.0, "#2a78d6"]]
FONT = dict(family="Pretendard, 'Noto Sans KR', 'Malgun Gothic', sans-serif", size=13)


def _layout(fig: go.Figure, title: str, height: int = 380) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=16)),
        height=height, margin=dict(l=10, r=10, t=50, b=10), font=FONT,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
        hoverlabel=dict(font_size=12),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    return fig


def price_line(df: pd.DataFrame, freq: str = "D", markets: list[str] | None = None) -> go.Figure:
    """① 가격 시계열. freq='D'(일) | 'M'(월 평균). 도매/소매 구분."""
    data = df if not markets else df[df["market"].isin(markets)]
    if freq == "M":
        data = (data.set_index("date").groupby("market")["price"].resample("MS").mean()
                .reset_index().dropna())
    unit = df["unit"].iloc[-1] if not df.empty else ""
    fig = px.line(data, x="date", y="price", color="market", color_discrete_map=MARKET_COLORS,
                  labels={"date": "일자" if freq == "D" else "월", "price": f"가격 ({unit})", "market": "구분"})
    fig.update_traces(line=dict(width=2), hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f}원<extra>%{fullData.name}</extra>")
    fig.update_layout(hovermode="x unified")
    return _layout(fig, f"느타리버섯 가격 추이 ({'일별' if freq == 'D' else '월평균'})")


def region_bar(df: pd.DataFrame, year: int | None = None) -> go.Figure:
    """② 지역별 생산량 막대 (선택 연도)."""
    year = year or int(df["year"].max())
    data = df[df["year"] == year].groupby("region", as_index=False)["production_ton"].sum()
    data = data.sort_values("production_ton")
    fig = px.bar(data, x="production_ton", y="region", orientation="h",
                 color="production_ton", color_continuous_scale=SEQUENTIAL_BLUE,
                 labels={"production_ton": "생산량 (톤)", "region": "시도"})
    fig.update_traces(marker_line_width=0, hovertemplate="%{y}<br>%{x:,.1f} 톤<extra></extra>")
    fig.update_layout(coloraxis_showscale=False, bargap=0.25)
    return _layout(fig, f"{year}년 시도별 생산량", height=max(380, 26 * len(data) + 80))


def production_yoy(df: pd.DataFrame, regions: list[str] | None = None) -> go.Figure:
    """③-a 연도별 생산량 증감률(%) 히트맵 (시도 × 연도)."""
    data = df if not regions else df[df["region"].isin(regions)]
    pivot = data.pivot_table(index="region", columns="year", values="production_ton", aggfunc="sum").sort_index()
    yoy = (pivot.pct_change(axis=1) * 100).iloc[:, 1:].round(1)
    bound = float(max(abs(yoy.min().min()), abs(yoy.max().max()), 1)) if not yoy.empty else 1.0
    fig = go.Figure(go.Heatmap(
        z=yoy.values, x=[str(c) for c in yoy.columns], y=yoy.index.tolist(),
        colorscale=DIVERGING, zmin=-bound, zmax=bound, xgap=2, ygap=2,
        colorbar=dict(title="%"), text=yoy.values, texttemplate="%{text:.1f}",
        hovertemplate="%{y} · %{x}년<br>전년 대비 %{z:+.1f}%<extra></extra>",
    ))
    return _layout(fig, "시도별 생산량 전년 대비 증감률 (%)", height=max(380, 24 * len(yoy) + 90))


def seasonality_heatmap(df: pd.DataFrame, market: str = "도매") -> go.Figure:
    """③-b 월별 계절성 히트맵 (연도 × 월 평균가격)."""
    data = df[df["market"] == market].copy()
    data["year"] = data["date"].dt.year
    data["month"] = data["date"].dt.month
    pivot = data.pivot_table(index="year", columns="month", values="price", aggfunc="mean").round(0)
    pivot = pivot.reindex(columns=range(1, 13))
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=[f"{m}월" for m in pivot.columns], y=[str(y) for y in pivot.index],
        colorscale=SEQUENTIAL_BLUE, xgap=2, ygap=2, colorbar=dict(title="원"),
        hovertemplate="%{y}년 %{x}<br>평균 %{z:,.0f}원<extra></extra>",
    ))
    return _layout(fig, f"{market} 가격 월별 계절성 (월평균)", height=320)
