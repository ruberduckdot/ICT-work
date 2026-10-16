"""Playwright로 Streamlit 4개 탭 실행 화면을 캡처해 docs/screenshots/에 저장.

사용:
  python scripts/capture_screens.py            # 현재 .env/환경변수의 LLM_PROVIDER로 캡처
  LLM_PROVIDER=gemini python scripts/capture_screens.py
mock 상태로 캡처하면 파일명에 `_mock`이 붙는다.
브라우저: PW_CHROMIUM_PATH > /opt/pw-browsers/chromium(사전 설치) > Playwright 기본 Chromium.
`playwright install`은 이 스크립트에서 실행하지 않는다.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen(url, timeout=3).status == 200:
                return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError(f"Streamlit 기동 실패: {url}")


def pick_image() -> Path:
    for d in (ROOT / "data" / "raw" / "images", ROOT / "data" / "sample" / "images"):
        files = sorted(p for ext in ("*.jpg", "*.jpeg", "*.png") for p in d.glob(ext))
        if files:
            return files[0]
    from src.data.make_sample import make_dummy_images

    return make_dummy_images()[0]


def launch_browser(p):
    exe = os.getenv("PW_CHROMIUM_PATH") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)
    return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()


def capture(port: int, suffix: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    url = f"http://localhost:{port}"
    saved: list[Path] = []
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(viewport={"width": 1440, "height": 1600}, device_scale_factor=1)
        page.goto(url)
        page.wait_for_selector("text=느타리버섯 가격 추이", timeout=120_000)
        page.wait_for_timeout(2500)

        def shot(name: str) -> None:
            page.wait_for_timeout(1200)
            assert page.locator("[data-testid='stException']").count() == 0, f"{name}: Streamlit 예외 발생"
            path = OUT / f"{name}{suffix}.png"
            # Streamlit은 본문이 내부 컨테이너에서 스크롤되므로 뷰포트 높이를 본문 높이에 맞춘 뒤 캡처
            height = page.evaluate("""() => {
                const m = document.querySelector('[data-testid=stMain]') || document.querySelector('section.main');
                return m ? m.scrollHeight : document.body.scrollHeight; }""")
            page.set_viewport_size({"width": 1440, "height": min(max(int(height) + 40, 900), 7000)})
            page.wait_for_timeout(800)
            page.evaluate("() => { const m = document.querySelector('[data-testid=stMain]'); if (m) m.scrollTop = 0; }")
            page.screenshot(path=str(path), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1600})
            saved.append(path)
            print(f"saved {path.relative_to(ROOT)}")

        def panel():
            return page.locator("[role=tabpanel]:visible")

        def fit_viewport() -> None:
            height = page.evaluate("""() => {
                const m = document.querySelector('[data-testid=stMain]') || document.querySelector('section.main');
                return m ? m.scrollHeight : document.body.scrollHeight; }""")
            page.set_viewport_size({"width": 1440, "height": min(max(int(height) + 40, 900), 7000)})
            page.wait_for_timeout(800)

        def element_shot(name: str, locator) -> None:
            """PPT 상세 슬라이드용 요소 단위 캡처 (전체 화면 캡처와 별도)."""
            fit_viewport()
            path = OUT / f"{name}{suffix}.png"
            locator.screenshot(path=str(path))
            page.set_viewport_size({"width": 1440, "height": 1600})
            saved.append(path)
            print(f"saved {path.relative_to(ROOT)}")

        def clip_shot(name: str, locators) -> None:
            """여러 요소를 감싸는 영역을 한 장으로 캡처."""
            fit_viewport()
            boxes = [loc.bounding_box() for loc in locators]
            x0, y0 = min(b["x"] for b in boxes) - 12, min(b["y"] for b in boxes) - 12
            x1 = max(b["x"] + b["width"] for b in boxes) + 12
            y1 = max(b["y"] + b["height"] for b in boxes) + 12
            path = OUT / f"{name}{suffix}.png"
            page.screenshot(path=str(path), clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}, full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1600})
            saved.append(path)
            print(f"saved {path.relative_to(ROOT)}")

        # 1) 대시보드 (+ KPI·차트 상세)
        shot("01_dashboard")
        charts = panel().locator(".js-plotly-plot")
        clip_shot("11_dashboard_kpi", [panel().locator("[data-testid=stAlert]").first,
                                       panel().locator("[data-testid=stMetric]").nth(2)])
        for i, name in enumerate(("12_chart_price_daily", "13_chart_region", "14_chart_yoy", "15_chart_seasonality")):
            element_shot(name, charts.nth(i))
        panel().get_by_text("월", exact=True).click()
        page.wait_for_timeout(2500)
        element_shot("16_chart_price_monthly", panel().locator(".js-plotly-plot").nth(0))

        # 2) 이미지 분석
        page.get_by_role("tab", name="이미지 분석").click()
        panel().locator("input[type=file]").set_input_files(str(pick_image()))
        page.wait_for_timeout(1500)
        panel().get_by_role("button", name="분석 실행").click()
        panel().get_by_text("구조화 출력(JSON)").wait_for(timeout=180_000)
        panel().get_by_text("구조화 출력(JSON)").click()
        shot("02_image_analysis")
        element_shot("21_vision_result", panel().locator("[data-testid=stHorizontalBlock]").first)

        # 3) AI 상담: 문서 → rag_search, 가격 → get_mushroom_price, 이미지 → analyze, 일지 → write_farm_diary
        page.get_by_role("tab", name="AI 상담").click()
        questions = [
            ("느타리버섯 자실체 생육기 적정 온도와 환기 관리는?", None),
            ("최근 가격 알려줘", None),
            ("이 버섯 상태 어때?", pick_image()),
            ("오늘 일지 써줘. 온도 16도 습도 90% CO2 950ppm, 3동 환기 2회", None),
        ]
        for q, img in questions:
            n = page.get_by_text("🔧 도구 호출").count()
            panel().locator("textarea").fill(q)
            if img:
                panel().locator("input[type=file]").set_input_files(str(img))
                page.wait_for_timeout(1500)
            panel().get_by_role("button", name="질문하기").click()
            page.wait_for_function(f"document.body.innerText.split('🔧 도구 호출').length - 1 > {n}", timeout=180_000)
            page.wait_for_timeout(1500)
        for exp in panel().get_by_text("🔧 도구 호출").all():
            exp.click()
            page.wait_for_timeout(300)
        shot("03_ai_chat")
        answers = panel().locator("[data-testid=stChatMessage]")
        for i, name in enumerate(("31_chat_rag", "32_chat_price", "33_chat_image", "34_chat_diary")):
            element_shot(name, answers.nth(2 * i + 1))  # 짝수=사용자, 홀수=Agent 응답
        element_shot("35_chat_trace_rag", panel().locator("[data-testid=stExpander]").first)

        # 4) 영농일지
        page.get_by_role("tab", name="영농일지").click()
        inputs = panel().locator("input[type=number]")
        for i, v in enumerate(("16.5", "90", "950")):
            inputs.nth(i).fill(v)
            inputs.nth(i).press("Enter")
        panel().locator("textarea").fill("3동 환기 2회 실시, 오염 의심 배지 2병 격리")
        page.wait_for_timeout(800)
        panel().get_by_role("button", name="일지 생성").click()
        panel().get_by_text("저장 완료").wait_for(timeout=180_000)
        shot("04_farm_diary")
        # 일지 본문을 담은 테두리 컨테이너 중 가장 안쪽 블록
        diary_box = panel().locator("[data-testid=stVerticalBlock]").filter(
            has=page.get_by_role("heading", name=re.compile("영농일지 —"))).last
        element_shot("41_diary_markdown", diary_box)
        browser.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "_mock" if get_settings().is_mock else ""
    port = args.port or free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        wait_http(f"http://localhost:{port}")
        capture(port, suffix)
    finally:
        proc.terminate()
        proc.wait(timeout=20)


if __name__ == "__main__":
    main()
