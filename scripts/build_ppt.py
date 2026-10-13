"""기능·구현 기술 설명 PPT 생성 (python-pptx) → docs/발표자료.pptx

사용: python scripts/build_ppt.py [--skip-tests]
- 실모델 캡처(파일명에 _mock 없음)가 있으면 우선 사용, 없으면 _mock 캡처를 쓰고 슬라이드에 'mock 캡처'로 표기
- 기본으로 pytest를 실제 실행해 그 결과 요약 줄을 '검증 결과' 슬라이드에 그대로 넣음
- 실제 구현된 내용만 기술함. 샘플 데이터 수치는 인용하지 않음
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "docs" / "발표자료.pptx"

FONT = "Malgun Gothic"
FOREST = RGBColor(0x1F, 0x3A, 0x2B)
MOSS = RGBColor(0x5E, 0x8C, 0x4A)
TINT = RGBColor(0xEE, 0xF3, 0xEA)
ACCENT = RGBColor(0xD9, 0x6C, 0x2C)
INK = RGBColor(0x22, 0x22, 0x22)
MUTED = RGBColor(0x5F, 0x63, 0x5C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
WARN_BG = RGBColor(0xFD, 0xF1, 0xE6)

W, H = Inches(13.333), Inches(7.5)
TMP = Path(tempfile.mkdtemp(prefix="ppt_"))


# ---------------------------------------------------------------- 공통 도우미
def _font(run, size, bold=False, color=INK, italic=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", FONT)


def text(slide, x, y, w, h, lines, size=16, color=INK, bold=False, bullet=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, space_after=6):
    """lines: str | list[str | (str, dict)]"""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    items = [lines] if isinstance(lines, str) else lines
    for i, item in enumerate(items):
        content, opt = (item, {}) if isinstance(item, str) else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = (("• " if bullet and not opt.get("nobullet") else "") + content)
        _font(r, opt.get("size", size), opt.get("bold", bold), opt.get("color", color), opt.get("italic", False))
    return box


def rect(slide, x, y, w, h, fill=TINT, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(1.25)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.shadow.inherit = False
    return s


def box_label(slide, x, y, w, h, title, body=None, fill=TINT, title_color=FOREST, body_color=INK, size=14):
    rect(slide, x, y, w, h, fill=fill)
    lines = [(title, {"bold": True, "color": title_color, "size": size + 1})]
    if body:
        lines += [(b, {"size": size - 1, "color": body_color}) for b in body]
    text(slide, x + 0.12, y + 0.08, w - 0.24, h - 0.16, lines, space_after=3)


def arrow(slide, x1, y1, x2, y2, color=MUTED):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(1.75)
    ln = c.line._get_or_add_ln()
    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)
    return c


def new_slide(prs, title=None, subtitle=None, dark=False):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = FOREST if dark else WHITE
    if title:
        text(s, 0.6, 0.4, 12.1, 0.8, title, size=32, bold=True, color=WHITE if dark else FOREST)
    if subtitle:
        text(s, 0.6, 1.12, 12.1, 0.5, subtitle, size=15, color=TINT if dark else MUTED)
    return s


def pick_shot(stem: str) -> tuple[Path | None, bool]:
    real = SHOTS / f"{stem}.png"
    mock = SHOTS / f"{stem}_mock.png"
    if real.exists():
        return real, False
    if mock.exists():
        return mock, True
    return None, False


def crop_to(path: Path, aspect: float, top: int = 0, left: int = 0) -> Path:
    img = Image.open(path)
    w = img.width - left
    h = min(int(w / aspect), img.height - top)
    out = TMP / f"{path.stem}_{top}_{left}.png"
    img.crop((left, top, left + w, top + h)).save(out)
    return out


def screenshot(slide, stem, x, y, w, h, top=0, left=0):
    path, is_mock = pick_shot(stem)
    if path is None:
        rect(slide, x, y, w, h, fill=TINT)
        text(slide, x, y + h / 2 - 0.3, w, 0.6, f"캡처 없음: {stem} (scripts/capture_screens.py 실행 필요)",
             size=13, color=MUTED, align=PP_ALIGN.CENTER)
        return
    img = crop_to(path, w / h, top, left)
    pic = slide.shapes.add_picture(str(img), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.line.color.rgb = RGBColor(0xC9, 0xD3, 0xC4)
    pic.line.width = Pt(1)
    label = "mock 모드 캡처 · 실모델 결과 아님" if is_mock else "실모델 캡처"
    text(slide, x, y + h + 0.05, w, 0.35, f"{path.name} · {label}", size=10, color=ACCENT if is_mock else MUTED)


def run_tests(skip: bool) -> str:
    if skip:
        return "테스트 미실행 (--skip-tests)"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                          capture_output=True, text=True, env={**__import__("os").environ, "LLM_PROVIDER": "mock"})
    lines = [l for l in proc.stdout.strip().splitlines() if re.search(r"\d+ (passed|failed)", l)]
    return lines[-1].strip("= ") if lines else f"pytest 실행 결과 해석 실패 (exit {proc.returncode})"


# ---------------------------------------------------------------- 슬라이드
def s_title(prs):
    s = new_slide(prs, dark=True)
    text(s, 0.8, 2.0, 11.5, 1.2, "멀티모달 AI Agent 기반 스마트 농업 서비스", size=40, bold=True, color=WHITE)
    text(s, 0.8, 3.15, 11.5, 0.7, "대상 작물: 느타리버섯 · Streamlit + LangGraph + VLM + RAG(Chroma)", size=20, color=TINT)
    rect(s, 0.8, 4.3, 5.6, 1.5, fill=RGBColor(0x2C, 0x4F, 0x3B))
    text(s, 1.0, 4.42, 5.3, 1.3, [("구현 범위", {"bold": True, "color": WHITE, "size": 15}),
                                  ("대시보드 · 이미지 분석 · AI 상담 · 영농일지 (4개 탭)", {"color": TINT, "size": 14}),
                                  ("Agent Tool 4종: rag_search / analyze / diary / price", {"color": TINT, "size": 14})])


def s_overview(prs):
    s = new_slide(prs, "과제 개요", "요구사항 6개 항목과 구현 위치")
    items = [
        ("1  데이터 선정", "가격(KAMIS)·지역 생산(KOSIS)·재배 매뉴얼·이미지\ndata/raw 우선, 없으면 SAMPLE"),
        ("2  대시보드", "Streamlit + Plotly 차트 4종\nKPI 3종 · 기간/지역 필터 · 출처 표기"),
        ("3  멀티모달·RAG", "VLM Zero-shot 이미지 분석(JSON)\n매뉴얼·분석결과 → Embedding → Chroma"),
        ("4  AI Agent", "LangGraph ToolNode 그래프\nTool 4종 자동 선택 · 최대 6회 반복"),
        ("5  UI", "이미지 업로드·질문 입력·대시보드\n검색 근거·Tool 이력·영농일지 출력"),
        ("6  제출물", "소스·캡처(Playwright)·PPT(python-pptx)\n제출 zip(scripts/make_zip.py)"),
    ]
    for i, (t, b) in enumerate(items):
        col, row = i % 3, i // 3
        x, y = 0.6 + col * 4.1, 1.8 + row * 2.6
        rect(s, x, y, 3.85, 2.3, fill=TINT)
        text(s, x + 0.2, y + 0.18, 3.5, 0.5, t, size=19, bold=True, color=FOREST)
        text(s, x + 0.2, y + 0.85, 3.5, 1.4, b.split("\n"), size=14, color=INK, space_after=4)


def s_data(prs):
    s = new_slide(prs, "데이터", "실데이터 투입 경로와 대체(SAMPLE) 규칙")
    rows = [
        ("구분", "투입 경로", "처리", "현재 상태"),
        ("가격", "data/raw/price/*.xlsx|csv\n(KAMIS 웹 다운로드)", "컬럼 매핑 dict, 실패 시 필요 컬럼 UI 표시\nKAMIS API는 키+품목코드 있을 때만", "SAMPLE"),
        ("지역 생산", "data/raw/production/*.csv\n(KOSIS 특용작물생산실적)", "wide→long, cp949/utf-8 자동 판별\n전국·계 행 제외", "SAMPLE"),
        ("재배 매뉴얼", "data/raw/docs/*.pdf|md", "PyPDFLoader, 파일명·페이지 메타데이터", "샘플 매뉴얼(일반 상식)"),
        ("이미지", "data/raw/images/*.jpg|png", "시연·테스트용(학습 없음, Zero-shot)", "mock 더미 이미지"),
    ]
    tbl = s.shapes.add_table(len(rows), 4, Inches(0.6), Inches(1.8), Inches(12.1), Inches(4.2)).table
    widths = [1.6, 3.6, 4.9, 2.0]
    for j, wv in enumerate(widths):
        tbl.columns[j].width = Inches(wv)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = FOREST if i == 0 else (TINT if i % 2 else WHITE)
            cell.text_frame.word_wrap = True
            for k, line in enumerate(val.split("\n")):
                p = cell.text_frame.paragraphs[0] if k == 0 else cell.text_frame.add_paragraph()
                r = p.add_run()
                r.text = line
                _font(r, 13 if i else 14, bold=(i == 0 or j == 0), color=WHITE if i == 0 else
                      (ACCENT if j == 3 else INK))
    rect(s, 0.6, 6.25, 12.1, 0.7, fill=WARN_BG)
    text(s, 0.8, 6.32, 11.8, 0.6, "샘플 가격·생산량은 합성값(is_sample=True)이며 실측 통계가 아님. 대시보드 상단과 각 차트 하단에 SAMPLE로 표기함",
         size=14, color=ACCENT, bold=True, anchor=MSO_ANCHOR.MIDDLE)


def s_arch(prs):
    s = new_slide(prs, "시스템 아키텍처", "공급자 생성은 src/llm/factory.py 한 곳에서만 수행")
    # UI
    box_label(s, 0.6, 1.75, 12.1, 0.95, "Streamlit UI (app.py)",
              ["📊 대시보드   🔬 이미지 분석   💬 AI 상담   📝 영농일지   · 사이드바: LLM_PROVIDER·모델·Embedding 표시"],
              fill=FOREST, title_color=WHITE, body_color=TINT)
    # 중간: Agent / Tools / factory
    box_label(s, 0.6, 3.15, 3.6, 1.6, "LangGraph Agent", ["agent 노드 ↔ ToolNode", "최대 6회 · 429/연결 오류 백오프 2회"])
    box_label(s, 4.6, 3.15, 4.3, 1.6, "Tools (src/agent/tools.py)",
              ["rag_search · analyze_mushroom_image", "write_farm_diary · get_mushroom_price"])
    box_label(s, 9.3, 3.15, 3.4, 1.6, "LLM factory", ["mock (기본, 키 불필요)", "gemini · ollama", "LLM_MODEL / VLM_MODEL 환경변수"])
    # 하단 계층
    bottom = [
        ("Chroma", ["manuals", "analysis_logs"]),
        ("Embedding", ["sentence-transformers", "e5 접두어 · 해싱 폴백"]),
        ("Vision", ["Pydantic JSON 스키마", "SHA-256 캐시"]),
        ("Data loaders", ["data/raw → SAMPLE", "KAMIS API(선택)"]),
        ("outputs/", ["diary/*.md", "cache · uploads"]),
    ]
    for i, (t, b) in enumerate(bottom):
        box_label(s, 0.6 + i * 2.45, 5.35, 2.25, 1.35, t, b, size=13)
    arrow(s, 2.4, 2.7, 2.4, 3.15)
    arrow(s, 4.2, 3.95, 4.6, 3.95)
    arrow(s, 9.3, 3.95, 8.9, 3.95)
    for x in (1.7, 4.15, 6.6, 9.05, 11.5):  # Tools → 하단 계층
        arrow(s, min(max(x, 4.9), 8.6), 4.75, x, 5.35)


def s_dashboard(prs):
    s = new_slide(prs, "대시보드 (탭 1)", "Streamlit + Plotly · 데이터 출처를 각 차트 하단에 표기")
    screenshot(s, "01_dashboard", 0.6, 1.7, 7.4, 5.2)
    text(s, 8.3, 1.8, 4.5, 5.0, [
        ("차트 4종", {"bold": True, "color": FOREST, "size": 17}),
        "① 가격 시계열 라인 — 일/월 전환, 도매·소매 구분",
        "② 시도별 생산량 가로 막대 — 연도 선택",
        "③ 시도별 생산량 전년 대비 증감률 히트맵",
        "④ 도매 가격 월별 계절성 히트맵 (연 × 월)",
        ("KPI · 필터", {"bold": True, "color": FOREST, "size": 17}),
        "최근 도매가 · 전월 대비 %(월평균) · 최대 생산 지역",
        "기간(date range) · 지역(multiselect)",
        ("이중 축 미사용, 범주색 고정 순서", {"color": MUTED, "size": 13}),
    ], size=14, space_after=7)


def s_vision(prs):
    s = new_slide(prs, "이미지 분석 (VLM Zero-shot)", "src/vision/analyzer.py · 학습 코드 없음(학습 데이터 없음)")
    screenshot(s, "02_image_analysis", 0.6, 1.7, 6.6, 4.9, left=300)
    box_label(s, 7.5, 1.75, 5.2, 2.35, "구조화 출력 스키마 (Pydantic)", [
        "growth_stage: 균사생장/원기형성/자실체생장/수확적기/과숙/판단불가",
        "disease_suspected: 정상/푸른곰팡이병/세균성갈색무늬병/버섯파리 피해/기타/판단불가",
        "confidence 0~1 · visual_evidence[] · recommended_actions[] · summary_ko",
    ], size=13)
    box_label(s, 7.5, 4.3, 5.2, 2.3, "처리 규칙", [
        "프롬프트: 관찰 근거만 기술, 불확실하면 판단불가·낮은 신뢰도",
        "파싱 실패 → 1회 재요청 → 실패 시 판단불가 반환(캐시 안 함)",
        "SHA-256(+공급자·모델) 키 캐시: 같은 이미지는 재호출 없음",
        "결과를 Chroma analysis_logs에 메타데이터와 함께 저장",
    ], size=13)


def s_rag(prs):
    s = new_slide(prs, "RAG: 재배 매뉴얼 검색", "src/rag/ingest.py · retriever.py · python -m src.rag.ingest 로 재색인")
    steps = [("문서 로딩", "pdf(PyPDFLoader)·md\n파일명·페이지 유지"), ("청킹", "Recursive splitter\n600자 / overlap 100"),
             ("Embedding", "multilingual-e5-small\nquery:/passage: 접두어"), ("Chroma", "컬렉션 manuals\ncosine 거리"),
             ("검색·판정", "top-k 4, 임계값 미만\n→ '문서 근거 없음'")]
    for i, (t, b) in enumerate(steps):
        x = 0.6 + i * 2.5
        rect(s, x, 1.9, 2.15, 1.9, fill=FOREST if i == 3 else TINT)
        text(s, x + 0.12, 2.0, 1.95, 1.75, [(t, {"bold": True, "size": 16, "color": WHITE if i == 3 else FOREST})] +
             [(l, {"size": 13, "color": TINT if i == 3 else INK}) for l in b.split("\n")], space_after=4)
        if i < 4:
            arrow(s, x + 2.15, 2.85, x + 2.5, 2.85)
    box_label(s, 0.6, 4.2, 6.0, 2.6, "출처 표기", [
        "모든 검색 결과에 파일명 · 페이지(PDF) · 청크 id · 유사도 포함",
        "Agent 답변 끝에 [번호]와 출처 인용 (시스템 프롬프트 규칙)",
        "UI: Tool 호출 이력 expander에 검색 근거 표 출력",
    ], size=14)
    box_label(s, 6.9, 4.2, 5.8, 2.6, "운영 처리", [
        "앱 최초 실행 시 vectorstore가 비면 자동 색인",
        "EMBEDDING_MODEL=BAAI/bge-m3 전환 가능 · 기본 임계값 0.855(e5-small 보정값)",
        "모델 로드 실패 시 해싱 폴백 + 사이드바 경고, 백엔드 변경 시 자동 재색인",
    ], fill=WARN_BG, title_color=ACCENT, size=14)


def s_agent(prs):
    s = new_slide(prs, "Agent · Tool 흐름", "src/agent/graph.py · StateGraph(agent ↔ ToolNode)")
    y0 = 2.15
    box_label(s, 0.6, y0, 2.6, 1.2, "사용자 입력", ["질문 + [첨부 이미지 경로]"])
    box_label(s, 3.8, y0, 2.8, 1.2, "agent 노드", ["LLM.bind_tools → tool_calls"], fill=FOREST, title_color=WHITE, body_color=TINT)
    box_label(s, 7.2, y0, 2.6, 1.2, "ToolNode", ["Tool 실행 → ToolMessage"])
    box_label(s, 10.4, y0, 2.3, 1.2, "최종 답변", ["출처·주의사항 포함"])
    arrow(s, 3.2, y0 + 0.6, 3.8, y0 + 0.6)
    arrow(s, 6.6, y0 + 0.4, 7.2, y0 + 0.4)
    arrow(s, 7.2, y0 + 0.85, 6.6, y0 + 0.85)
    # 종료 경로: agent 위로 우회해 최종 답변으로 (박스를 가로지르지 않게)
    for x1, y1, x2, y2 in ((5.2, y0, 5.2, 1.8), (5.2, 1.8, 11.55, 1.8)):
        ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        ln.line.color.rgb = MOSS
        ln.line.width = Pt(1.75)
    arrow(s, 11.55, 1.8, 11.55, y0, color=MOSS)
    text(s, 7.6, 1.42, 4.0, 0.35, "tool_calls 없음 또는 6회 도달 → 종료", size=12, color=MOSS)
    tools = [
        ("rag_search(query)", "재배 방법·환경·방제 질문, 문서 요약"),
        ("analyze_mushroom_image(image_path, question)", "첨부 이미지 상태 질문"),
        ("write_farm_diary(date, notes)", "\"오늘 일지 써줘\" — 메모의 온도·습도·CO2 반영"),
        ("get_mushroom_price(period)", "가격·시세 질문 — 1w/1m/3m/6m/1y/all"),
    ]
    for i, (t, b) in enumerate(tools):
        col, row = i % 2, i // 2
        box_label(s, 0.6 + col * 6.15, 3.75 + row * 1.3, 5.95, 1.1, t, [b], size=13)
    text(s, 0.6, 6.45, 12.1, 0.6, "반복 6회 제한: 마지막 회차는 Tool 없이 답변 생성 · 429/연결 오류는 지수 백오프 2회 후 'API 한도 초과 또는 모델 서버 미연결' 표시",
         size=13, color=MUTED)


def s_ui(prs):
    s = new_slide(prs, "UI: AI 상담 (탭 3)", "검색 근거와 Tool 호출 이력을 st.expander로 표시 · 대화 이력은 session_state")
    screenshot(s, "03_ai_chat", 0.6, 1.7, 8.0, 5.2, top=0, left=300)
    text(s, 8.9, 1.8, 3.9, 5.0, [
        ("화면 구성", {"bold": True, "color": FOREST, "size": 17}),
        "질문 입력 + 이미지 첨부(선택)",
        "업로드 이미지는 outputs/uploads/에 저장 후 경로를 메시지에 첨부",
        "Tool별 표시: 입력 JSON, 검색 근거 표, 가격 요약 표, 일지 저장 경로",
        ("mock 모드 답변은 도구 결과를 그대로 묶은 고정 형식이며 LLM 요약이 아님", {"color": ACCENT, "size": 13}),
    ], size=14, space_after=8)


def s_diary(prs):
    s = new_slide(prs, "영농일지 (탭 4 · write_farm_diary)", "src/diary/writer.py · outputs/diary/YYYY-MM-DD.md 저장 + 다운로드")
    screenshot(s, "04_farm_diary", 0.6, 1.7, 7.0, 5.2, left=300)
    text(s, 7.9, 1.8, 4.9, 5.0, [
        ("고정 Markdown 양식", {"bold": True, "color": FOREST, "size": 17}),
        "1 날짜 · 2 재배사 환경(℃/%/ppm 표) · 3 생육 상태",
        "4 병해충 · 5 작업 내용 · 6 익일 계획",
        ("입력", {"bold": True, "color": FOREST, "size": 17}),
        "날짜, 온도·습도·CO2 직접 입력, 작업 메모",
        "당일 이미지 분석 결과 선택(캐시에서 조회)",
        ("LLM은 '익일 계획'만 생성 · 입력에 없는 수치 생성 금지", {"color": MUTED, "size": 13}),
    ], size=14, space_after=7)


def s_demo(prs):
    s = new_slide(prs, "시연 시나리오", "LLM_PROVIDER=mock으로 키 없이 전체 흐름 재현 가능")
    steps = [
        ("대시보드", "SAMPLE 배지 확인 → 기간·지역 필터, 일/월 전환"),
        ("이미지 분석", "이미지 업로드 → 분석 실행 → JSON·캐시 적중 확인(재실행)"),
        ("문서 질의", "\"자실체 생육기 적정 온도와 환기 관리는?\" → rag_search, 출처 표"),
        ("이미지 질의", "AI 상담에 이미지 첨부 + \"상태 어때?\" → analyze_mushroom_image"),
        ("가격 질의", "\"최근 가격 알려줘\" → get_mushroom_price(1m)"),
        ("영농일지", "\"오늘 일지 써줘. 온도 16도 습도 90%\" 또는 탭 4에서 작성 → md 다운로드"),
    ]
    for i, (t, b) in enumerate(steps):
        y = 1.8 + i * 0.85
        c = rect(s, 0.6, y, 0.62, 0.62, fill=FOREST, shape=MSO_SHAPE.OVAL)
        text(s, 0.6, y + 0.06, 0.62, 0.5, str(i + 1), size=18, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        text(s, 1.45, y + 0.08, 2.4, 0.5, t, size=17, bold=True, color=FOREST)
        text(s, 3.9, y + 0.1, 8.8, 0.5, b, size=15)


def s_verify(prs, test_line: str):
    s = new_slide(prs, "검증 결과", "모든 검증은 LLM_PROVIDER=mock으로 수행 (키 없이)")
    rect(s, 0.6, 1.8, 5.2, 2.2, fill=FOREST)
    text(s, 0.8, 1.95, 4.9, 0.5, "pytest (빌드 시 실제 실행 결과)", size=15, color=TINT)
    text(s, 0.8, 2.55, 4.9, 1.3, test_line, size=26, bold=True, color=WHITE)
    checks = [
        "test_llm: mock이 표준 tool_calls AIMessage 생성, 429 백오프",
        "test_data: 샘플 대체, KAMIS 컬럼 매핑, KOSIS wide→long(cp949)",
        "test_rag: 실 e5 Embedding으로 샘플 질의 3건 출처 반환, 무관 질의 '문서 근거 없음'",
        "test_vision: 스키마 준수, 캐시 재호출 없음, 1회 재요청, analysis_logs",
        "test_agent: 질의 유형별 Tool 선택 4건, 반복 6회 제한",
    ]
    text(s, 6.2, 1.8, 6.5, 3.0, checks, size=14, bullet=True, space_after=8)
    rect(s, 0.6, 4.5, 12.1, 2.3, fill=WARN_BG)
    text(s, 0.85, 4.6, 11.6, 2.1, [
        ("실모델 검증 필요 (이 개발 환경에서 미수행)", {"bold": True, "color": ACCENT, "size": 16}),
        "Gemini·Ollama 실제 호출(Tool 선택 품질, VLM 판독 정확도) — API 키·모델 서버 없음",
        "실 Embedding은 검증 완료(e5-small): 관련 질의 top 유사도 ≥ 0.876, 무관 질의 ≤ 0.833 → 임계값 0.855 (샘플 문서 7청크 기준)",
        "KAMIS Open API 파라미터·응답 형식 — [미확인], 접속 불가",
    ], size=14, space_after=5)


def s_limits(prs):
    s = new_slide(prs, "한계와 개선점")
    rows = [
        ("데이터", "가격·생산 통계와 이미지가 샘플/더미", "KAMIS·KOSIS 파일과 실제 재배 사진 투입"),
        ("Vision", "Zero-shot VLM, 정량 정확도 미측정", "라벨링 이미지셋 구축 후 정확도 평가, 필요 시 ViT/YOLO 미세조정"),
        ("RAG", "임계값 0.855는 샘플 문서 7청크로만 보정", "공식 매뉴얼 색인 후 질의셋으로 임계값 재보정"),
        ("Agent", "mock은 키워드 규칙이라 복합 질의 미처리", "실모델로 다중 Tool 연쇄 호출 평가"),
        ("가격 API", "KAMIS 파라미터·품목코드 [미확인]", "공식 문서 확인 후 품목코드 .env 설정"),
    ]
    for i, (k, a, b) in enumerate(rows):
        y = 1.5 + i * 1.08
        rect(s, 0.6, y, 2.0, 0.88, fill=FOREST)
        text(s, 0.6, y, 2.0, 0.88, k, size=16, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        rect(s, 2.75, y, 4.85, 0.88, fill=TINT)
        text(s, 2.9, y, 4.6, 0.88, a, size=14, anchor=MSO_ANCHOR.MIDDLE)
        rect(s, 7.75, y, 4.95, 0.88, fill=WHITE, line=MOSS)
        text(s, 7.9, y, 4.7, 0.88, "→ " + b, size=14, color=FOREST, anchor=MSO_ANCHOR.MIDDLE)


def build(skip_tests: bool = False) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    test_line = run_tests(skip_tests)
    s_title(prs)
    s_overview(prs)
    s_data(prs)
    s_arch(prs)
    s_dashboard(prs)
    s_vision(prs)
    s_rag(prs)
    s_agent(prs)
    s_ui(prs)
    s_diary(prs)
    s_demo(prs)
    s_verify(prs, test_line)
    s_limits(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT.relative_to(ROOT)} ({len(prs.slides)} slides) · pytest: {test_line}")
    return OUT


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tests", action="store_true")
    build(ap.parse_args().skip_tests)
