"""Streamlit 진입점: 대시보드 / 이미지 분석 / AI 상담 / 영농일지."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import DATA_RAW, DATA_SAMPLE, ROOT, UPLOAD_DIR, get_settings
from src.dashboard import charts
from src.data import loaders
from src.llm.factory import LLMConfigError, LLMUnavailableError, UNAVAILABLE_MESSAGE, describe_provider

st.set_page_config(page_title="느타리버섯 스마트 농업 AI", page_icon="🍄", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def _load_price():
    return loaders.load_price_data()


@st.cache_data(ttl=600, show_spinner=False)
def _load_production():
    return loaders.load_production_data()


def source_caption(result: loaders.LoadResult) -> None:
    st.caption(f"데이터 출처: **{'SAMPLE (합성값, 실측 아님)' if result.is_sample else result.source_label}**")


@st.cache_resource(show_spinner="재배 매뉴얼 색인 확인 중…")
def init_index() -> dict:
    """앱 최초 실행 시 vectorstore가 비어 있으면 자동 색인."""
    from src.rag.embeddings import get_embeddings
    from src.rag.ingest import ensure_index

    result = ensure_index()
    _, backend, fallback = get_embeddings()
    return {"indexed_now": result is not None, "backend": backend, "fallback": fallback}


def render_sidebar(index_info: dict) -> None:
    info = describe_provider()
    st.sidebar.header("모델 설정")
    st.sidebar.markdown(f"- LLM_PROVIDER: `{info['provider']}`\n- LLM: `{info['llm_model']}`\n- VLM: `{info['vlm_model']}`")
    if info["provider"] == "mock":
        st.sidebar.warning("데모 모드: mock 모델은 실제 생성·이미지 분석을 하지 않고 규칙 기반 고정 응답을 반환함")
    st.sidebar.markdown(f"- Embedding: `{index_info['backend']}`")
    if index_info["fallback"]:
        st.sidebar.warning(f"Embedding 실모델(`{get_settings().embedding_model}`) 로드 실패 → 해싱 폴백 사용 중. "
                           "sentence-transformers·torch 설치 후 재실행 권장")
    if index_info["indexed_now"]:
        st.sidebar.success("vectorstore가 비어 있어 매뉴얼을 자동 색인함")


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


# ---------------------------------------------------------------- 공통: 업로드 저장
def save_upload(uploaded) -> Path:
    data = uploaded.getvalue()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in uploaded.name)
    path = UPLOAD_DIR / f"{hashlib.sha256(data).hexdigest()[:12]}_{safe}"
    if not path.exists():
        path.write_bytes(data)
    return path


def md_safe(text: str) -> str:
    """'12~18 ℃' 같은 범위 표기가 Markdown 취소선으로 렌더링되지 않게 물결표를 이스케이프."""
    return text.replace("~", "\\~")


def rel(path: Path | str) -> str:
    p = Path(path)
    return str(p.relative_to(ROOT)) if p.is_absolute() and p.is_relative_to(ROOT) else str(p)


def demo_images() -> list[Path]:
    return sorted(p for d in (DATA_RAW / "images", DATA_SAMPLE / "images")
                  for ext in ("*.jpg", "*.jpeg", "*.png") for p in d.glob(ext))


# ---------------------------------------------------------------- 탭 2: 이미지 분석
def render_analysis_result(record: dict) -> None:
    r = record["result"]
    if record.get("is_mock"):
        st.warning("mock 모델 결과: 이미지를 실제로 분석하지 않은 고정 응답임")
    c1, c2, c3 = st.columns(3)
    c1.metric("생육 단계", r["growth_stage"])
    c2.metric("병해충 의심", r["disease_suspected"])
    c3.metric("신뢰도", f"{r['confidence']:.2f}")
    st.markdown(md_safe(f"**요약**: {r['summary_ko']}"))
    st.markdown("**관찰 근거**\n" + "\n".join(f"- {e}" for e in r["visual_evidence"] or ["없음"]))
    st.markdown("**권장 조치**\n" + "\n".join(f"- {a}" for a in r["recommended_actions"] or ["없음"]))
    st.caption(f"캐시 {'적중(재호출 없음)' if record['cached'] else '미적중(신규 호출)'} · SHA-256 {record['sha256'][:16]}… · "
               f"{record['provider']}/{record['model']} · 파싱 {record['parse_status']}")
    with st.expander("구조화 출력(JSON)"):
        st.json(r)


def render_vision_tab() -> None:
    from src.vision import analyzer

    st.subheader("생육 상태·병해충 이미지 분석 (VLM Zero-shot)")
    col_in, col_out = st.columns([1, 2])
    with col_in:
        uploaded = st.file_uploader("이미지 업로드 (jpg/png)", type=["jpg", "jpeg", "png"], key="vision_upload")
        samples = demo_images()
        sample = st.selectbox("또는 시연용 이미지 선택", ["(선택 안 함)"] + [rel(p) for p in samples], key="vision_sample")
        run = st.button("분석 실행", type="primary", key="vision_run")
    path = save_upload(uploaded) if uploaded else (ROOT / sample if sample != "(선택 안 함)" else None)
    if path:
        col_in.image(str(path), caption=rel(path), use_container_width=True)
    with col_out:
        if run and path is None:
            st.info("이미지를 업로드하거나 선택해야 함")
        elif run:
            try:
                with st.spinner("이미지 분석 중…"):
                    record = analyzer.analyze_image(path)
                st.session_state["last_analysis"] = record
            except LLMUnavailableError:
                st.error(UNAVAILABLE_MESSAGE)
            except LLMConfigError as exc:
                st.error(f"모델 설정 오류: {exc}")
        if st.session_state.get("last_analysis"):
            render_analysis_result(st.session_state["last_analysis"])


# ---------------------------------------------------------------- 탭 3: AI 상담
TOOL_LABELS = {"rag_search": "재배 문서 검색", "analyze_mushroom_image": "이미지 분석",
               "write_farm_diary": "영농일지 작성", "get_mushroom_price": "가격 조회"}


def render_trace(trace: list[dict]) -> None:
    for i, t in enumerate(trace, 1):
        with st.expander(f"🔧 도구 호출 {i}: {t['tool']} ({TOOL_LABELS.get(t['tool'], '')})"):
            st.markdown("**입력**")
            st.code(json.dumps(t["args"], ensure_ascii=False, indent=2), language="json")
            art = t.get("artifact") or {}
            if art.get("type") == "rag":
                if art["no_evidence"]:
                    st.warning(f"문서 근거 없음 (임계값 {art['threshold']})")
                else:
                    st.markdown("**검색 근거**")
                    st.dataframe(pd.DataFrame([{"출처": h["citation"], "유사도": h["score"],
                                                "본문(앞부분)": h["text"][:120]} for h in art["hits"]]),
                                 use_container_width=True, hide_index=True)
            elif art.get("type") == "price" and art.get("rows"):
                st.markdown(f"**조회 결과** (출처: {art['source']})")
                st.dataframe(pd.DataFrame(art["rows"]), use_container_width=True, hide_index=True)
            elif art.get("type") == "diary":
                st.markdown(f"**저장 경로**: `{rel(art['path'])}`")
            elif art.get("type") == "vision" and art.get("result"):
                st.json(art["result"])
            st.markdown("**결과 요약**")
            st.text(t.get("result") or "")


def render_chat_tab() -> None:
    from src.agent.graph import run_agent

    st.subheader("AI 영농 상담 (LangGraph Agent)")
    st.caption("질문 유형에 따라 Agent가 rag_search / analyze_mushroom_image / write_farm_diary / get_mushroom_price 중에서 골라 호출함")
    chat = st.session_state.setdefault("chat", [])
    for turn in chat:
        with st.chat_message(turn["role"]):
            if turn.get("image"):
                st.image(turn["image"], width=160)
            st.markdown(md_safe(turn["content"]))
            if turn.get("trace"):
                render_trace(turn["trace"])

    with st.form("chat_form", clear_on_submit=True):
        question = st.text_area("질문", placeholder="예) 자실체 생육기 적정 온도는? / 최근 가격 알려줘 / 오늘 일지 써줘", key="chat_q")
        image = st.file_uploader("이미지 첨부(선택)", type=["jpg", "jpeg", "png"], key="chat_img")
        submitted = st.form_submit_button("질문하기", type="primary")
    if st.button("대화 초기화", key="chat_reset"):
        st.session_state["chat"], st.session_state["lc_history"] = [], []
        st.rerun()

    if submitted and question.strip():
        img_path = rel(save_upload(image)) if image else None
        with st.spinner("Agent 처리 중…"):
            res = run_agent(question, image_path=img_path, history=st.session_state.get("lc_history", []))
        chat.append({"role": "user", "content": question, "image": str(ROOT / img_path) if img_path else None})
        if res["error"]:
            st.error(res["answer"])
        chat.append({"role": "assistant", "content": res["answer"], "trace": res["trace"]})
        st.session_state.setdefault("lc_history", []).extend(res["messages"])
        st.rerun()


# ---------------------------------------------------------------- 탭 4: 영농일지
def render_diary_tab() -> None:
    from src.diary import writer
    from src.vision import analyzer

    st.subheader("영농일지 자동 작성")
    c1, c2, c3, c4 = st.columns(4)
    day = c1.date_input("날짜", value=date.today(), key="diary_date")
    temp = c2.number_input("온도 (℃)", value=None, step=0.5, format="%.1f", key="diary_temp")
    hum = c3.number_input("상대습도 (%)", value=None, min_value=0.0, max_value=100.0, step=1.0, key="diary_hum")
    co2 = c4.number_input("CO2 (ppm)", value=None, min_value=0.0, step=50.0, key="diary_co2")
    notes = st.text_area("작업 메모", placeholder="예) 3동 환기 2회, 오염 배지 4병 반출", key="diary_notes")

    records = analyzer.list_cached_analyses()
    labels = {f"{r['file_name']} · {r['analyzed_at']} · {r['result']['growth_stage']}/{r['result']['disease_suspected']}"
              f"{' · mock' if r.get('is_mock') else ''}": r for r in records}
    same_day = [k for k, r in labels.items() if r["analyzed_at"].startswith(day.isoformat())]
    picked = st.multiselect("당일 이미지 분석 결과 선택", list(labels), default=same_day,
                            key=f"diary_picks_{day.isoformat()}_{len(records)}")

    if st.button("일지 생성", type="primary", key="diary_run"):
        with st.spinner("일지 작성 중…"):
            md = writer.build_diary(day.isoformat(), temp, hum, co2, notes, [labels[k] for k in picked])
            path = writer.save_diary(day.isoformat(), md)
        st.session_state["diary"] = {"md": md, "path": str(path)}
    if st.session_state.get("diary"):
        d = st.session_state["diary"]
        st.success(f"저장 완료: {rel(d['path'])}")
        st.download_button("Markdown 다운로드", d["md"], file_name=Path(d["path"]).name, mime="text/markdown",
                           key="diary_dl")
        with st.container(border=True):
            st.markdown(md_safe(d["md"]))


def main() -> None:
    st.title("🍄 느타리버섯 스마트 농업 AI 서비스")
    render_sidebar(init_index())
    tabs = st.tabs(["📊 대시보드", "🔬 이미지 분석", "💬 AI 상담", "📝 영농일지"])
    with tabs[0]:
        render_dashboard()
    with tabs[1]:
        render_vision_tab()
    with tabs[2]:
        render_chat_tab()
    with tabs[3]:
        render_diary_tab()


main()
