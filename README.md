# 멀티모달 AI Agent 기반 스마트 농업 서비스 (느타리버섯)

Streamlit 4개 탭(대시보드 / 이미지 분석 / AI 상담 / 영농일지)과 LangGraph Agent(Tool 4종)로 구성한 느타리버섯 재배 지원 서비스임.
API 키 없이 `LLM_PROVIDER=mock`(기본값)으로 전체 기능을 실행·테스트할 수 있고, 키나 로컬 모델 서버가 있으면 `gemini`·`ollama`로 전환함.

> **데이터 주의**: 저장소에 포함된 가격·생산량은 **합성 샘플(실측 아님, `is_sample=True`)** 이며 화면에 SAMPLE로 표시됨. 샘플 매뉴얼은 일반 재배 상식 수준 문서임.

## 1. 요구사항 ↔ 구현

| 요구사항 | 구현 | 위치 |
|---|---|---|
| 1. 데이터 선정 | 가격(KAMIS)·지역 생산(KOSIS)·재배 매뉴얼·이미지. `data/raw/` 우선, 없으면 샘플 | `src/data/loaders.py`, `src/data/kamis.py`, `src/data/make_sample.py` |
| 2. 대시보드 | Plotly 차트 4종, KPI 3종, 기간·지역 필터, 차트별 출처 표기 | `src/dashboard/charts.py`, `app.py` |
| 3. 멀티모달·RAG | VLM Zero-shot 이미지 분석(Pydantic JSON), 매뉴얼·분석결과 Embedding → Chroma(`manuals`, `analysis_logs`) | `src/vision/analyzer.py`, `src/rag/*` |
| 4. AI Agent | LangGraph(agent ↔ ToolNode), Tool 4종, 최대 반복 6회 | `src/agent/graph.py`, `src/agent/tools.py` |
| 5. UI | 이미지 업로드·질문 입력, 대시보드, 검색 근거·Tool 이력, 영농 상담·영농일지 | `app.py` |
| 6. 제출물 | 캡처·PPT·zip 생성 스크립트 | `scripts/` , `docs/` |

Tool 4종

| Tool | 호출 조건 | 반환 |
|---|---|---|
| `rag_search(query)` | 재배 방법·환경·병해충 방제·문서 요약 질문 | 관련 구절 + 출처(파일명·페이지·청크 id·유사도). 임계값 미만이면 "문서 근거 없음" |
| `analyze_mushroom_image(image_path, question)` | 메시지에 `[첨부 이미지 경로: ...]`가 있는 이미지 질문 | 생육 단계·병해충·신뢰도·근거·권장 조치(JSON) |
| `write_farm_diary(date, notes)` | "오늘 일지 써줘" 등 | `outputs/diary/YYYY-MM-DD.md` 저장 |
| `get_mushroom_price(period)` | 가격·시세 질문 | 도매/소매 기간 요약(1w/1m/3m/6m/1y/all) |

## 2. 디렉터리 구조

```
app.py                     Streamlit 진입점 (탭 4개)
src/config.py              환경변수 로딩
src/llm/factory.py         LLM·VLM 공급자 생성 (gemini/ollama/mock), 429·연결 오류 백오프
src/llm/mock.py            Fake Chat 모델 (키워드 기반 tool_calls 생성)
src/data/                  loaders.py(가격·생산), kamis.py(Open API, 선택), make_sample.py(샘플 생성)
src/dashboard/charts.py    Plotly 차트
src/vision/analyzer.py     VLM 이미지 분석 (JSON 스키마, SHA-256 캐시, analysis_logs 저장)
src/rag/                   embeddings.py, ingest.py, retriever.py
src/agent/                 tools.py(Tool 4종), graph.py(LangGraph)
src/diary/writer.py        영농일지 양식·저장
data/raw/{price,production,docs,images}/   사용자 실데이터 (.gitkeep만 커밋)
data/sample/               샘플 데이터 (SAMPLE)
outputs/diary|cache|uploads/               생성물
tests/                     pytest (mock으로 전부 통과)
scripts/                   capture_screens.py, build_ppt.py, make_zip.py
docs/screenshots/, docs/발표자료.pptx
```

## 3. 설치

Python 3.11 기준.

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
# sentence-transformers는 torch가 필요함. GPU가 없으면 CPU 전용 휠을 먼저 설치하면 용량이 작음
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env                 # 필요한 값만 채움
```

- OpenAI 패키지는 사용하지 않음.
- 최초 실행 시 Embedding 모델(`intfloat/multilingual-e5-small`)을 Hugging Face에서 내려받음. 내려받지 못하거나 torch가 없으면 **해싱 폴백 Embedding**으로 동작하고 사이드바에 경고가 표시됨(검색 품질 낮음).
- 캡처 스크립트용 브라우저: `playwright install chromium` (이미 Chromium이 있으면 `PW_CHROMIUM_PATH`로 경로 지정).

## 4. 환경변수 (`.env`)

| 변수 | 설명 |
|---|---|
| `LLM_PROVIDER` | `mock`(기본) \| `gemini` \| `ollama` |
| `LLM_MODEL` | Agent·영농일지 모델명. gemini/ollama 사용 시 필수 (코드에 모델명 하드코딩 없음) |
| `VLM_MODEL` | 이미지 분석 모델명. 미지정 시 `LLM_MODEL` 사용 |
| `GOOGLE_API_KEY` | gemini 사용 시 필수 |
| `OLLAMA_BASE_URL` | 기본 `http://localhost:11434` |
| `EMBEDDING_MODEL` | 기본 `intfloat/multilingual-e5-small`, `BAAI/bge-m3` 전환 가능, `hash`는 폴백 강제 |
| `RAG_SCORE_THRESHOLD` | 실 Embedding 유사도 임계값(기본 0.80, 실데이터로 조정 필요) |
| `KAMIS_API_KEY`, `KAMIS_API_ID` | 선택. 있으면 KAMIS Open API 우선 조회 |
| `KAMIS_ITEM_CODE`, `KAMIS_KIND_CODE`, `KAMIS_CATEGORY_CODE`, `KAMIS_RANK_CODE` | KAMIS 품목·품종 코드. 추측해 넣지 않았으므로 KAMIS 코드표에서 확인 후 지정 |

공급자별 예시

```bash
# mock (키 불필요, 데모 모드)
LLM_PROVIDER=mock

# gemini
LLM_PROVIDER=gemini
GOOGLE_API_KEY=<발급받은 키>
LLM_MODEL=<Google AI Studio에서 확인한 Gemini 모델명>
VLM_MODEL=<이미지 입력을 지원하는 Gemini 모델명>

# ollama (로컬 서버)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=<tool calling 지원 모델명>   # ollama pull <모델명>
VLM_MODEL=<비전 지원 모델명>
```

## 5. 실행

```bash
streamlit run app.py                      # .env의 LLM_PROVIDER 사용
LLM_PROVIDER=mock streamlit run app.py    # 키 없이 데모 모드
```

- 사이드바에 현재 공급자·모델명·Embedding 백엔드가 표시됨(mock이면 "데모 모드" 경고).
- 앱 최초 실행 시 `vectorstore/`가 비어 있으면 매뉴얼을 자동 색인함.
- 429(Rate limit)·연결 오류는 지수 백오프로 2회 재시도 후 "API 한도 초과 또는 모델 서버 미연결"을 표시함.

## 6. 데이터 투입 (사용자 준비)

이 저장소는 외부 사이트에서 데이터를 자동 다운로드하지 않음. 아래 파일을 직접 받아 경로에 넣으면 다음 실행부터 샘플 대신 사용됨.

| 데이터 | 넣을 경로 | 받을 곳 | 비고 |
|---|---|---|---|
| 느타리버섯 가격 | `data/raw/price/*.xlsx` 또는 `*.csv` | KAMIS 농산물유통정보(https://www.kamis.or.kr) 가격 조회 화면의 엑셀 다운로드 [메뉴 경로 미확인] | 필요한 컬럼: 날짜(일자/날짜/regday…), 가격(가격/평균가격…). 도매·소매는 `구분` 컬럼 또는 파일명의 "도매"/"소매"로 판별. 매핑 실패 시 필요한 컬럼이 대시보드에 표시됨 |
| 시도별 생산량 | `data/raw/production/*.csv` | KOSIS 국가통계포털(https://kosis.kr) 「특용작물생산실적」 버섯류 시도별 통계표 CSV 다운로드 [통계표 위치 미확인] | 연도가 열로 펼쳐진 wide 형식 자동 변환, cp949/utf-8 자동 판별, `전국`·`계` 행 제외, `느타리` 품목 자동 필터 |
| 재배 매뉴얼 | `data/raw/docs/*.pdf` 또는 `*.md` | 농촌진흥청 농사로(https://www.nongsaro.go.kr) 등 공식 재배 매뉴얼 [자료 위치 미확인] | 넣은 뒤 `python -m src.rag.ingest`로 재색인 |
| 생육·병해충 이미지 | `data/raw/images/*.jpg|png` | 직접 촬영 | 시연·테스트용. 학습에 쓰지 않음(Zero-shot VLM) |

샘플 재생성: `python -m src.data.make_sample`

## 7. 주요 명령

```bash
pytest                                     # 전체 테스트 (키 없이 mock)
python -m src.rag.ingest                   # 매뉴얼 재색인
python scripts/capture_screens.py          # 4개 탭 캡처 → docs/screenshots/ (mock이면 *_mock.png)
python scripts/build_ppt.py                # docs/발표자료.pptx 재빌드 (pytest 실행 결과 반영)
python scripts/make_zip.py --name 홍길동    # 홍길동_과제제출.zip 생성
```

zip 포함: 소스(app.py, src, scripts, tests), requirements.txt, README.md, .env.example, docs/, data/sample/ · 제외: .env, vectorstore/, outputs/, venv, data/raw 원본

## 8. 실모델로 캡처·PPT 다시 만들기 (PC)

1. 3장 설치 후 `.env`에 `LLM_PROVIDER=gemini`(또는 `ollama`)와 `LLM_MODEL`·`VLM_MODEL`·키를 설정함.
2. 실데이터를 `data/raw/`에 넣고 `python -m src.rag.ingest`로 재색인함. 실제 버섯 사진을 `data/raw/images/`에 넣음(캡처 스크립트가 첫 번째 이미지를 업로드함).
3. `streamlit run app.py`로 사이드바의 공급자·Embedding 백엔드(해싱 폴백 경고가 없는지)를 확인함.
4. `python scripts/capture_screens.py` → `_mock`이 없는 `docs/screenshots/0N_*.png` 생성.
5. `python scripts/build_ppt.py` → 실모델 캡처가 우선 사용됨.
6. `python scripts/make_zip.py --name <이름>`.

## 9. 검증 현황과 한계

- 이 저장소의 테스트·캡처·PPT는 모두 `LLM_PROVIDER=mock`으로 생성됨. mock은 이미지를 실제로 분석하지 않고 '판단불가'를 반환하며, 상담 답변은 도구 결과를 묶은 고정 형식임.
- 개발 환경에서는 Hugging Face 접속이 차단되어 **실 Embedding 검증을 하지 못했고 해싱 폴백으로 검증함**. `RAG_SCORE_THRESHOLD`(0.80)는 실모델 기준으로 조정 필요.
- KAMIS Open API의 엔드포인트·파라미터·응답 형식은 **[미확인]**(코드 주석 표기). 확인 전까지는 파일 다운로드 방식을 권장함.
- ViT·YOLO 학습 코드는 없음(학습 데이터 없음). 이미지 분석은 VLM Zero-shot이며 정확도는 측정하지 않음.
