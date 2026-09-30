"""Data packs: carry finished runs from the compute machine to the demo machine.

The preset library is computed where there are cores to spare, and shown on a
laptop that may have no network at the venue. A pack is one file that holds
the run folders, their library index entries and the processed files the API
reads for them, with a checksum for every file.

Format (`.fgpack`, a zip)
-------------------------
    fgpack.json         format version, name, creation time, FloodGuard version,
                        run ids, library index entries, attribution, and one row
                        per file: data-dir-relative path, size, sha256
    payload/<relpath>   the files, at their paths relative to the data dir

Import is all-or-nothing
------------------------
Every check runs before the first byte is written: format version, every
checksum, every path. Paths are relative and may not climb out of the data
directory (absolute paths, drive letters, backslashes and `..` are refused).
A file that already exists with the same checksum is skipped; one that exists
with DIFFERENT content stops the import, because a run shown over someone
else's files is a wrong answer that looks right. Library index entries are
merged; an existing entry is never replaced by a different one.

There is no HTTP endpoint for this on purpose: import writes arbitrary files
into the data directory, which is a CLI operation, not a web one.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from floodguard import library as lib

FORMAT_VERSION = 1
SUFFIX = ".fgpack"
MANIFEST_NAME = "fgpack.json"
PAYLOAD_PREFIX = "payload/"

#: Sources whose derivatives travel in a pack, with the attribution they require.
ATTRIBUTION = [
    "Terrain: Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus 2014-2018, "
    "provided under COPERNICUS by the European Union and ESA.",
    "Land cover: ESA WorldCover 10 m 2021 v200, CC BY 4.0.",
    "Population: WorldPop constrained 2020 (UN-adjusted), CC BY 4.0.",
    "Exposure counts derived from OpenStreetMap data, (c) OpenStreetMap contributors, ODbL.",
    "Inundation results: FloodGuard India model output; see each run's result.json "
    "for its engine, resolution, warnings and provenance.",
]

#: Per-scenario processed files the API reads when showing a run (the reservoir
#: curve and the cross-section endpoint read preprocess.json).
PROCESSED_FILES = ("preprocess.json",)


class PackError(RuntimeError):
    """A pack that cannot be written or read, with the reason in plain words."""


@dataclass
class PackSummary:
    path: Path
    name: str
    run_ids: list[str]
    files: int
    bytes: int
    copied: int = 0
    already_present: int = 0
    index_added: list[str] = field(default_factory=list)
    index_kept: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": str(self.path), "name": self.name, "run_ids": self.run_ids,
            "files": self.files, "bytes": self.bytes, "copied": self.copied,
            "already_present": self.already_present, "index_added": self.index_added,
            "index_kept": self.index_kept,
        }


# --- helpers ------------------------------------------------------------------------


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _member_digest(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name) as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def checked_relpath(rel: str) -> PurePosixPath:
    """A data-dir-relative path from a pack, or PackError if it could escape."""
    if not rel or "\\" in rel or ":" in rel:
        raise PackError(f"refusing unsafe path in pack: {rel!r}")
    path = PurePosixPath(rel)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PackError(f"refusing unsafe path in pack: {rel!r}")
    return path


def _version() -> str:
    try:
        from floodguard import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def select_runs(data_dir: Path, patterns: Iterable[str]) -> list[str]:
    """Completed run ids (folders holding result.json) matching any glob pattern."""
    runs_root = Path(data_dir) / "runs"
    found = sorted(
        p.parent.name for p in runs_root.glob("*/result.json")
    ) if runs_root.exists() else []
    chosen = [r for r in found if any(fnmatch.fnmatch(r, pat) for pat in patterns)]
    return chosen


# --- export -------------------------------------------------------------------------


def export_pack(
    data_dir: Path,
    run_ids: list[str],
    out_path: Path,
    *,
    name: str | None = None,
    include_processed: bool = True,
) -> PackSummary:
    """Write a pack holding these runs. Raises PackError before writing on any problem."""
    data_dir = Path(data_dir).resolve()
    if not run_ids:
        raise PackError("no completed runs matched; nothing to pack")

    files: dict[str, Path] = {}
    scenario_ids: set[str] = set()
    for run_id in run_ids:
        run_dir = data_dir / "runs" / run_id
        result = run_dir / "result.json"
        if not result.exists():
            raise PackError(f"run {run_id!r} has no result.json; only finished runs can be packed")
        data = json.loads(result.read_text(encoding="utf-8"))
        if data.get("scenario_id"):
            scenario_ids.add(data["scenario_id"])
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                files[path.relative_to(data_dir).as_posix()] = path

    if include_processed:
        for sid in sorted(scenario_ids):
            for fname in PROCESSED_FILES:
                for path in sorted((data_dir / "processed" / sid).rglob(fname)):
                    files[path.relative_to(data_dir).as_posix()] = path

    index = lib.load_index(data_dir)
    index_entries = {
        key: entry for key, entry in index.items() if entry.get("run_id") in set(run_ids)
    }

    out_path = Path(out_path)
    if out_path.suffix != SUFFIX:
        out_path = out_path.with_suffix(SUFFIX)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + ".partial")

    rows = []
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for rel in sorted(files):
            source = files[rel]
            zf.write(source, PAYLOAD_PREFIX + rel)
            rows.append({
                "path": rel, "size": source.stat().st_size, "sha256": _digest(source),
                "mtime": source.stat().st_mtime,
            })
        manifest = {
            "format_version": FORMAT_VERSION,
            "name": name or out_path.stem,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "floodguard_version": _version(),
            "run_ids": list(run_ids),
            "library_index": index_entries,
            "attribution": ATTRIBUTION,
            "files": rows,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    # Renamed into place last: an interrupted export never looks like a pack.
    partial.replace(out_path)

    return PackSummary(
        path=out_path, name=manifest["name"], run_ids=list(run_ids),
        files=len(rows), bytes=out_path.stat().st_size,
    )


# --- import -------------------------------------------------------------------------


def import_pack(data_dir: Path, pack_path: Path) -> PackSummary:
    """Verify a pack completely, then copy its files and merge its index entries."""
    data_dir = Path(data_dir).resolve()
    pack_path = Path(pack_path)
    if not pack_path.is_file():
        raise PackError(f"no such pack: {pack_path}")
    try:
        zf = zipfile.ZipFile(pack_path)
    except zipfile.BadZipFile as exc:
        raise PackError(f"{pack_path} is not a FloodGuard pack (not a zip): {exc}") from exc

    with zf:
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError as exc:
            raise PackError(f"{pack_path} has no {MANIFEST_NAME}; not a FloodGuard pack") from exc
        except ValueError as exc:
            raise PackError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
        if manifest.get("format_version") != FORMAT_VERSION:
            raise PackError(
                f"pack format {manifest.get('format_version')!r} is not supported "
                f"(this FloodGuard reads format {FORMAT_VERSION})"
            )

        # ---- verify everything; nothing is written in this block ----
        names = set(zf.namelist())
        rows: dict[str, dict[str, Any]] = {}
        for row in manifest.get("files", []):
            rel = str(checked_relpath(str(row.get("path", ""))))
            member = PAYLOAD_PREFIX + rel
            if member not in names:
                raise PackError(f"manifest lists {rel} but the pack does not contain it")
            if _member_digest(zf, member) != row.get("sha256"):
                raise PackError(f"checksum mismatch for {rel}: the pack is damaged or was edited")
            rows[rel] = row
        extra = [
            n for n in names
            if n.startswith(PAYLOAD_PREFIX) and not n.endswith("/")
            and n[len(PAYLOAD_PREFIX):] not in rows
        ]
        if extra:
            raise PackError(f"pack holds files its manifest does not list: {extra[:3]}")

        pending: list[tuple[str, Path]] = []
        present = 0
        for rel, row in rows.items():
            target = data_dir.joinpath(*PurePosixPath(rel).parts)
            if data_dir not in target.resolve().parents:
                raise PackError(f"refusing unsafe path in pack: {rel!r}")
            if target.exists():
                if _digest(target) == row["sha256"]:
                    present += 1
                    continue
                raise PackError(
                    f"{target} already exists with different content. Import stopped "
                    f"rather than overwrite it or show a run over the wrong files."
                )
            pending.append((rel, target))

        incoming = manifest.get("library_index") or {}
        current = lib.load_index(data_dir)
        added, kept = [], []
        for key, entry in incoming.items():
            lib.parse_key(key)  # raises on a malformed key
            if key in current:
                if current[key] != entry:
                    # Same key, different record, and the run files did not
                    # conflict: keep what this machine already has.
                    kept.append(key)
                continue
            added.append(key)

        # ---- write ----
        for rel, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".partial")
            with zf.open(PAYLOAD_PREFIX + rel) as src, tmp.open("wb") as dst:
                for block in iter(lambda: src.read(1 << 20), b""):
                    dst.write(block)
            tmp.replace(target)
            mtime = rows[rel].get("mtime")
            if isinstance(mtime, (int, float)):
                # Keep the original time, so "is this cache newer than the run"
                # checks give the same answer on the receiving machine.
                os.utime(target, (mtime, mtime))

    if added:
        merged = lib.load_index(data_dir)
        for key in added:
            merged[key] = incoming[key]
        lib.write_index(data_dir, merged)

    return PackSummary(
        path=pack_path, name=manifest.get("name", pack_path.stem),
        run_ids=list(manifest.get("run_ids", [])), files=len(rows),
        bytes=pack_path.stat().st_size, copied=len(pending), already_present=present,
        index_added=added, index_kept=kept,
    )
