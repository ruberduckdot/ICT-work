# 멀티모달 AI Agent 기반 스마트 농업 서비스 (느타리버섯)

> 초안. 단계별 구현이 끝나면 설치·실행·데이터 투입 절차를 보완함.

- UI: Streamlit (탭 4개: 대시보드 / 이미지 분석 / AI 상담 / 영농일지)
- Agent: LangChain + LangGraph (ToolNode 기반 그래프), Tool 4종
- LLM·VLM: `LLM_PROVIDER` = `mock`(기본) | `gemini` | `ollama`
- RAG: sentence-transformers 로컬 Embedding + Chroma
