import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 모든 테스트는 키 없이 mock 공급자로 수행
os.environ["LLM_PROVIDER"] = "mock"
for key in ("GOOGLE_API_KEY", "KAMIS_API_KEY", "KAMIS_API_ID"):
    os.environ.pop(key, None)
