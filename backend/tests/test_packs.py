"""Data packs: round trip, all-or-nothing import, and path safety."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from floodguard import cli, packs
from floodguard import library as lib

KEY = "tehri_bhagirathi__complete_dam_break__frl"


def _library_run(data_dir: Path, key: str = KEY, payload: str = "depth") -> str:
    run_id = lib.run_id_for(key)
    run = data_dir / "runs" / run_id
    run.mkdir(parents=True)
    (run / "result.json").write_text(json.dumps({"run_id": run_id, "scenario_id": key.split("__")[0]}))
    (run / "max_depth.tif").write_bytes(payload.encode() * 100)
    (run / "frames").mkdir()
    (run / "frames" / "f0.bin").write_bytes(b"\x00\x01" * 50)
    lib.record(data_dir, key, {"run_id": run_id, "status": "succeeded",
                               "completed_utc": "2026-09-30T05:00:00Z"})
    return run_id


def test_round_trip_copies_runs_processed_files_and_index(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    run_id = _library_run(src)
    pre = src / "processed" / "tehri_bhagirathi" / "preprocess.json"
    pre.parent.mkdir(parents=True)
    pre.write_text('{"reservoir": {}}')
    (src / "runs" / "other_run").mkdir(parents=True)
    (src / "runs" / "other_run" / "result.json").write_text("{}")

    runs = packs.select_runs(src, ["lib_*"])
    assert runs == [run_id]
    summary = packs.export_pack(src, runs, tmp_path / "demo", name="demo")
    assert summary.path.name == "demo.fgpack"
    assert summary.files == 4  # result, raster, frame, preprocess.json

    result = packs.import_pack(dst, summary.path)
    assert result.copied == 4 and result.index_added == [KEY]
    assert (dst / "runs" / run_id / "frames" / "f0.bin").read_bytes() == b"\x00\x01" * 50
    assert (dst / "processed" / "tehri_bhagirathi" / "preprocess.json").exists()
    assert lib.lookup(dst, KEY) is not None
    assert not (dst / "runs" / "other_run").exists()

    again = packs.import_pack(dst, summary.path)
    assert again.copied == 0 and again.already_present == 4 and again.index_added == []


def test_import_merges_with_an_existing_index(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _library_run(src)
    other = "hirakud_mahanadi__complete_dam_break__frl"
    _library_run(dst, other)
    pack = packs.export_pack(src, packs.select_runs(src, ["lib_*"]), tmp_path / "p.fgpack")
    packs.import_pack(dst, pack.path)
    assert set(lib.load_index(dst)) == {KEY, other}


def test_conflicting_file_aborts_before_writing_anything(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _library_run(src)
    pack = packs.export_pack(src, packs.select_runs(src, ["lib_*"]), tmp_path / "p.fgpack")
    _library_run(dst, payload="DIFFERENT")  # same run id, different raster
    before = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*"))
    with pytest.raises(packs.PackError, match="different content"):
        packs.import_pack(dst, pack.path)
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*")) == before


def test_tampered_payload_is_refused(tmp_path):
    src = tmp_path / "src"
    _library_run(src)
    pack = packs.export_pack(src, packs.select_runs(src, ["lib_*"]), tmp_path / "p.fgpack")
    tampered = tmp_path / "t.fgpack"
    with zipfile.ZipFile(pack.path) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith("max_depth.tif"):
                data = b"fake" + data
            zout.writestr(item, data)
    with pytest.raises(packs.PackError, match="checksum mismatch"):
        packs.import_pack(tmp_path / "dst", tampered)
    assert not (tmp_path / "dst" / "runs").exists()


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd", "C:/x", "runs\\x", "a/../../b", ""])
def test_unsafe_paths_are_refused(bad):
    with pytest.raises(packs.PackError):
        packs.checked_relpath(bad)


def test_zip_slip_member_is_refused(tmp_path):
    evil = tmp_path / "evil.fgpack"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("payload/../outside.txt", "x")
        zf.writestr(packs.MANIFEST_NAME, json.dumps({
            "format_version": packs.FORMAT_VERSION, "files": [
                {"path": "../outside.txt", "size": 1, "sha256": "0"}],
        }))
    with pytest.raises(packs.PackError, match="unsafe path"):
        packs.import_pack(tmp_path / "dst", evil)
    assert not (tmp_path / "outside.txt").exists()


def test_unknown_format_and_non_zip_are_refused(tmp_path):
    notzip = tmp_path / "x.fgpack"
    notzip.write_text("hello")
    with pytest.raises(packs.PackError, match="not a zip"):
        packs.import_pack(tmp_path, notzip)
    future = tmp_path / "f.fgpack"
    with zipfile.ZipFile(future, "w") as zf:
        zf.writestr(packs.MANIFEST_NAME, json.dumps({"format_version": 99, "files": []}))
    with pytest.raises(packs.PackError, match="not supported"):
        packs.import_pack(tmp_path, future)


def test_export_with_no_matching_runs_is_an_error(tmp_path):
    with pytest.raises(packs.PackError, match="nothing to pack"):
        packs.export_pack(tmp_path, [], tmp_path / "p.fgpack")


def test_cli_round_trip(tmp_path, capsys):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _library_run(src)
    out = tmp_path / "demo.fgpack"
    assert cli.main(["pack", "export", "--runs", "lib_*", "--out", str(out),
                     "--data-dir", str(src)]) == 0
    assert cli.main(["pack", "import", str(out), "--data-dir", str(dst)]) == 0
    assert "presets added   : 1" in capsys.readouterr().out
    assert cli.main(["pack", "import", str(tmp_path / "missing.fgpack"),
                     "--data-dir", str(dst)]) == 1


def test_import_preserves_file_times(tmp_path):
    import os

    src, dst = tmp_path / "src", tmp_path / "dst"
    run_id = _library_run(src)
    old = 1_700_000_000.0
    target = src / "runs" / run_id / "max_depth.tif"
    os.utime(target, (old, old))
    pack = packs.export_pack(src, packs.select_runs(src, ["lib_*"]), tmp_path / "p.fgpack")
    packs.import_pack(dst, pack.path)
    assert (dst / "runs" / run_id / "max_depth.tif").stat().st_mtime == old
