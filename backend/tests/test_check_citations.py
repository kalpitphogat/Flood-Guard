"""scripts/check_citations.py resolves doc references against the tree."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_citations.py"
spec = importlib.util.spec_from_file_location("check_citations", SCRIPT)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def test_verdicts(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "pkg" / "a").mkdir(parents=True)
    (repo / "pkg" / "b").mkdir(parents=True)
    (repo / "pkg" / "a" / "main.py").write_text("x = 1\ny = 2\n")
    (repo / "pkg" / "b" / "main.py").write_text("z = 3\n")
    (repo / "pkg" / "a" / "solo.py").write_text("\n" * 10)
    (repo / ".github").mkdir()
    (repo / ".github" / "ci.yml").write_text("on: push\n")
    doc = repo / "doc.md"
    doc.write_text(
        "`pkg/a/main.py:2` `pkg/a/solo.py:50` `gone/file.py` `main.py` `result.json` "
        "`.github/ci.yml` `../elsewhere.md`\n"
    )
    monkeypatch.setattr(cc, "REPO", repo)
    index = cc.suffix_index(cc.source_files(repo))
    statuses = [row[0] for row in cc.check(doc, index, {})]
    assert statuses == [
        "OK", "LINE_OOR", "FILE_GONE", "AMBIGUOUS", "OUTPUT_NAME", "OK", "OUTSIDE_REPO",
    ]
