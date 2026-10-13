"""제출 zip 생성: [이름]_과제제출.zip

사용: python scripts/make_zip.py --name 홍길동
포함: 소스(app.py, src/, scripts/, tests/), requirements.txt, README.md, .env.example, docs/, data/sample/
제외: .env, vectorstore/, outputs/(cache·uploads·diary), venv, __pycache__, data/raw/ 원본(.gitkeep만 포함)
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["app.py", "requirements.txt", "README.md", ".env.example", "src", "scripts", "tests", "docs", "data/sample"]
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", "venv", "vectorstore", ".git"}
EXCLUDE_NAMES = {".env"}


def iter_files():
    for item in INCLUDE:
        p = ROOT / item
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.relative_to(ROOT).parts) & EXCLUDE_DIRS) and f.name not in EXCLUDE_NAMES \
                        and f.suffix != ".pyc":
                    yield f
    # data/raw는 폴더 구조(.gitkeep)만 포함
    yield from sorted((ROOT / "data" / "raw").rglob(".gitkeep"))
    yield ROOT / "outputs" / "diary" / ".gitkeep"


def make_zip(name: str, out_dir: Path = ROOT) -> Path:
    out = out_dir / f"{name}_과제제출.zip"
    prefix = f"{name}_과제제출"
    files = [f for f in iter_files() if f.exists()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f"{prefix}/{f.relative_to(ROOT).as_posix()}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="제출자 이름")
    args = ap.parse_args()
    out = make_zip(args.name)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    print(f"saved {out.name} · 파일 {len(names)}개 · {out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
