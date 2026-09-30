"""Check every backticked code reference in the docs against the working tree.

The handoff notes, the methodology and CLAUDE.md point at code as
`backend/floodguard/pipeline.py:531` or just `engines/swe_fv.py`. Those
pointers rot silently: a file moves, a function drifts 200 lines, and the prose
still reads as verified. This resolves each one and reports:

    OK          the file exists (and the cited line is inside it)
    FILE_GONE   no file in the tree matches the cited path
    OUTPUT_NAME a bare file name that no source matches (e.g. `result.json`,
                a run artefact); listed in the tally, not treated as a defect
    OUTSIDE_REPO a `../` path, outside this repository; listed, not checked
    LINE_OOR    the file exists but has fewer lines than cited
    AMBIGUOUS   a bare fragment that several files match (`main.py`); widen it

The working tree is searched, not only git-tracked files, because much of the
code is uncommitted while a round is in progress.

    python scripts/check_citations.py                  # CLAUDE.md, README, docs/*.md
    python scripts/check_citations.py docs/HANDOFF.md  # one file
    python scripts/check_citations.py --only FILE_GONE # a worklist

Exit status is 1 when anything is not OK.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUFFIXES = ("py", "ts", "tsx", "js", "jsx", "md", "yaml", "yml", "toml", "json", "css", "html")
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache"}
#: Top-level folders holding generated data, not source (checked by direct path only).
SKIP_TOP = {"data", "outputs", "runs"}
#: Documents about OTHER repositories (the reference audit), not this one.
EXTERNAL_DOCS = {"AUDIT.md"}

REFERENCE = re.compile(
    r"`(?P<path>[A-Za-z0-9_./-]+\.(?:" + "|".join(SUFFIXES) + r"))"
    r"(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?"
    r"(?:::[A-Za-z0-9_.]+)?`"
)


def source_files(root: Path) -> list[str]:
    out = []
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if parts[0] in SKIP_TOP or any(part in SKIP_DIRS for part in parts):
            continue
        if path.is_file() and path.suffix.lstrip(".") in SUFFIXES:
            out.append(path.relative_to(root).as_posix())
    return out


def suffix_index(paths: list[str]) -> dict[str, list[str]]:
    """Every trailing fragment -> the files ending with it."""
    index: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        parts = p.split("/")
        for i in range(len(parts)):
            index["/".join(parts[i:])].append(p)
    return index


def check(doc: Path, index: dict[str, list[str]], line_counts: dict[str, int]):
    rows = []
    for n, text in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
        for m in REFERENCE.finditer(text):
            cited = m.group("path")
            if cited.startswith("./"):  # not lstrip: `.github/...` must keep its dot
                cited = cited[2:]
            matches = index.get(cited, [])
            if not matches and (REPO / cited).is_file():
                matches = [cited]  # generated data cited by its full path
            if cited.startswith("../"):
                status = "OUTSIDE_REPO"  # e.g. a handoff kept beside the repo
            elif not matches and "/" not in cited:
                status = "OUTPUT_NAME"  # a bare artefact name such as result.json
            elif not matches:
                status = "FILE_GONE"
            elif len(matches) > 1 and cited not in matches:
                status = "AMBIGUOUS"
            else:
                target = cited if cited in matches else matches[0]
                last = int(m.group("end") or m.group("start") or 0)
                if last and last > line_counts.setdefault(
                    target, len((REPO / target).read_text(encoding="utf-8", errors="replace").splitlines())
                ):
                    status = "LINE_OOR"
                else:
                    status = "OK"
            rows.append((status, f"{doc.relative_to(REPO).as_posix()}:{n}", m.group(0)))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("docs", nargs="*")
    parser.add_argument(
        "--only", choices=["OK", "FILE_GONE", "LINE_OOR", "AMBIGUOUS", "OUTPUT_NAME", "OUTSIDE_REPO"]
    )
    args = parser.parse_args(argv)

    docs = [Path(d).resolve() for d in args.docs] or [
        REPO / "CLAUDE.md", REPO / "README.md",
        *(d for d in sorted((REPO / "docs").glob("*.md")) if d.name not in EXTERNAL_DOCS),
    ]
    index = suffix_index(source_files(REPO))
    counts: dict[str, int] = {}
    rows = [row for doc in docs if doc.exists() for row in check(doc, index, counts)]

    for status, where, ref in rows:
        if status not in ("OK", "OUTPUT_NAME", "OUTSIDE_REPO") and (args.only is None or args.only == status):
            print(f"{status:<10} {where:<32} {ref}")
        elif args.only == "OK" and status == "OK":
            print(f"{status:<10} {where:<32} {ref}")
    tally = Counter(status for status, _, _ in rows)
    print(f"\n{len(rows)} references: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0 if set(tally) <= {"OK", "OUTPUT_NAME", "OUTSIDE_REPO"} else 1


if __name__ == "__main__":
    sys.exit(main())
