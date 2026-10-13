import zipfile

from scripts import make_zip


def test_zip_contents(tmp_path):
    out = make_zip.make_zip("테스트", out_dir=tmp_path)
    names = zipfile.ZipFile(out).namelist()
    prefix = "테스트_과제제출/"
    assert all(n.startswith(prefix) for n in names)
    rel = {n[len(prefix):] for n in names}
    for must in ("app.py", "requirements.txt", "README.md", "src/agent/graph.py", "data/sample/docs/oyster_mushroom_guide.md",
                 "scripts/build_ppt.py"):
        assert must in rel
    assert not any(r == ".env" or r.startswith(("vectorstore/", "outputs/cache/", "outputs/uploads/", ".venv/")) for r in rel)
    assert not any("__pycache__" in r for r in rel)
    assert all(r.endswith(".gitkeep") for r in rel if r.startswith("data/raw/"))
