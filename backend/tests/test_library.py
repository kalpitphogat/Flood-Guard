"""Preset library: keys, levels, scenario overrides, the index, and the batch.

None of these run a solver: `simulate` is replaced where the batch is tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from floodguard import cli
from floodguard import library as lib
from floodguard.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]
TEHRI = REPO / "data" / "scenarios" / "tehri_bhagirathi.yaml"
HIRAKUD = REPO / "data" / "scenarios" / "hirakud_mahanadi.yaml"


@pytest.fixture()
def tehri() -> Scenario:
    return Scenario.from_yaml(TEHRI)


@pytest.fixture()
def hirakud() -> Scenario:
    return Scenario.from_yaml(HIRAKUD)


# --- keys and levels ----------------------------------------------------------------


def test_key_round_trip():
    key = lib.preset_key("tehri_bhagirathi", "complete_dam_break", "frl")
    assert key == "tehri_bhagirathi__complete_dam_break__frl"
    assert lib.parse_key(key) == ("tehri_bhagirathi", "complete_dam_break", "frl", 120.0)
    fine = lib.preset_key("tehri_bhagirathi", "complete_dam_break", "frl", 60.0)
    assert fine == "tehri_bhagirathi__complete_dam_break__frl__r60"
    assert lib.parse_key(fine) == ("tehri_bhagirathi", "complete_dam_break", "frl", 60.0)
    assert lib.preset_key("t", "complete_dam_break", "mid", 92.5).endswith("__r92p5")
    assert lib.run_id_for(key) == "lib_tehri_bhagirathi__complete_dam_break__frl"


@pytest.mark.parametrize("bad", ["", "a__b", "a__b__c__d", "a____c", "a__b__c__r120", "a__b__c__rx", "a__b__c__d__e"])
def test_malformed_keys_are_rejected(bad):
    with pytest.raises(ValueError):
        lib.parse_key(bad)


def test_levels_come_from_the_yaml(tehri, hirakud):
    assert lib.level_values(tehri) == {"frl": 830.0, "mid": 785.0, "mddl": 740.0}
    h = lib.level_values(hirakud)
    assert h["frl"] == pytest.approx(192.02)
    assert h["mddl"] == pytest.approx(179.83)
    # (192.02 + 179.83) / 2 = 185.925, rounded to 0.01 m.
    assert h["mid"] == pytest.approx(185.93, abs=0.006)


def test_missing_mddl_gives_frl_only(tehri):
    no_mddl = tehri.model_copy(deep=True)
    no_mddl.dam.mddl_m = None
    assert lib.level_values(no_mddl) == {"frl": 830.0}
    assert [p.level for p in lib.iter_presets(no_mddl)] == ["frl"]


def test_missing_frl_gives_no_presets(tehri):
    bare = tehri.model_copy(deep=True)
    bare.dam.frl_m = None
    bare.dam.mddl_m = None
    assert lib.level_values(bare) == {}
    assert list(lib.iter_presets(bare)) == []


def test_priority_order_puts_complete_break_at_frl_first(tehri):
    presets = list(lib.iter_presets(tehri, include_unmodelled=True))
    assert presets[0].key == "tehri_bhagirathi__complete_dam_break__frl"
    types = [p.scenario_type for p in presets]
    assert types == sorted(types, key=lib.PRESET_TYPES.index)
    assert len(presets) == 9


def test_unmodelled_types_are_listed_but_never_computed(tehri):
    """partial_breach / overtopping are the same computation as a complete break
    today; a separate run would store the same numbers under another name."""
    computed = list(lib.iter_presets(tehri))
    assert {p.scenario_type for p in computed} == {"complete_dam_break"}
    listed = list(lib.iter_presets(tehri, include_unmodelled=True))
    assert {p.scenario_type for p in listed if not p.modelled} == {"partial_breach", "overtopping"}
    with pytest.raises(ValueError, match="Not modelled distinctly"):
        lib.build_preset_scenario(tehri, "overtopping", "frl")


# --- scenario overrides -------------------------------------------------------------


def test_build_preset_scenario_overrides(tehri):
    s = lib.build_preset_scenario(tehri, "complete_dam_break", "mddl")
    assert s.id == tehri.id  # processed-data folder key is unchanged
    assert s.scenario_type.value == "complete_dam_break"
    assert s.reservoir.initial_level_m == 740.0
    assert s.domain.resolution_m == lib.LIBRARY_RESOLUTION_M == 120.0
    assert s.engines == ["swe_fv"]
    assert s.solver.duration_hours == tehri.solver.duration_hours
    # the base scenario is not mutated
    assert tehri.domain.resolution_m == 30.0
    assert tehri.engines == ["swe_fv", "sph_swe"]


def test_unknown_level_is_rejected(tehri):
    with pytest.raises(ValueError):
        lib.build_preset_scenario(tehri, "complete_dam_break", "spillway_crest")


def test_quick_settings(tehri):
    q = lib.apply_quick_settings(tehri)
    assert q.domain.resolution_m == 200.0
    assert q.solver.duration_hours == 1.0
    assert q.engines == ["swe_fv"]
    assert tehri.domain.resolution_m == 30.0


# --- index --------------------------------------------------------------------------


def _fake_result(data_dir: Path, key: str, **extra) -> Path:
    path = lib.result_path(data_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"completed_utc": "2026-09-30T05:00:00Z", **extra}))
    return path


def test_index_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    lib.write_index(tmp_path, {"a": {"x": 1}})
    lib.record(tmp_path, "b", {"x": 2})
    assert lib.load_index(tmp_path) == {"a": {"x": 1}, "b": {"x": 2}}
    assert [p.name for p in lib.library_dir(tmp_path).iterdir()] == ["index.json"]


def test_corrupt_index_reads_as_empty(tmp_path):
    lib.library_dir(tmp_path).mkdir(parents=True)
    lib.index_path(tmp_path).write_text("{not json")
    assert lib.load_index(tmp_path) == {}


def test_lookup_requires_result_json_and_success(tmp_path, tehri):
    preset = next(lib.iter_presets(tehri))
    entry = lib.entry_for(preset, duration_hours=6.0, completed_utc="2026-09-30T05:00:00Z",
                          wall_seconds=200.0, status="succeeded")
    lib.record(tmp_path, preset.key, entry)
    assert lib.lookup(tmp_path, preset.key) is None  # no result.json yet

    _fake_result(tmp_path, preset.key)
    assert lib.lookup(tmp_path, preset.key)["wall_seconds"] == 200.0

    lib.record(tmp_path, preset.key, {**entry, "status": "failed"})
    assert lib.lookup(tmp_path, preset.key) is None


# --- the batch ----------------------------------------------------------------------


def _run_batch(monkeypatch, tmp_path, calls, argv, fail_keys=()):
    import floodguard.pipeline as pipeline

    def fake_simulate(scenario, data_dir, *, run_id, engines, run_meta, progress, **_):
        calls.append((run_id, scenario.reservoir.initial_level_m, scenario.domain.resolution_m,
                      tuple(engines), run_meta["run_mode"]))
        if run_meta["library_key"] in fail_keys:
            raise RuntimeError("synthetic failure")
        _fake_result(data_dir, run_meta["library_key"], run_mode="precomputed")
        return SimpleNamespace(warnings=[])

    monkeypatch.setattr(pipeline, "simulate", fake_simulate)
    monkeypatch.setattr(pipeline, "ensure_inputs", lambda *a, **k: [])
    return cli.main(["precompute", "--data-dir", str(tmp_path), *argv])


def test_precompute_runs_in_order_and_records_the_index(monkeypatch, tmp_path):
    calls = []
    rc = _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi"])
    assert rc == 0
    assert [c[0] for c in calls] == [
        "lib_tehri_bhagirathi__complete_dam_break__frl",
        "lib_tehri_bhagirathi__complete_dam_break__mid",
        "lib_tehri_bhagirathi__complete_dam_break__mddl",
    ]
    assert all(c[2] == 120.0 and c[3] == ("swe_fv",) and c[4] == "precomputed" for c in calls)
    assert [c[1] for c in calls] == [830.0, 785.0, 740.0]
    index = lib.load_index(tmp_path)
    assert len(index) == 3
    assert all(e["status"] == "succeeded" and e["wall_seconds"] is not None
               for e in index.values())


def test_precompute_resumes_and_force_recomputes(monkeypatch, tmp_path):
    calls = []
    _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi", "--limit", "1"])
    assert len(calls) == 1
    calls.clear()
    _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi"])
    assert [c[1] for c in calls] == [785.0, 740.0]  # frl was already done
    calls.clear()
    _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi", "--force"])
    assert len(calls) == 3


def test_one_failure_does_not_stop_the_batch(monkeypatch, tmp_path):
    calls = []
    bad = "tehri_bhagirathi__complete_dam_break__mid"
    rc = _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi"],
                    fail_keys={bad})
    assert rc == 1
    assert len(calls) == 3
    index = lib.load_index(tmp_path)
    assert index[bad]["status"] == "failed"
    assert "synthetic failure" in index[bad]["error"]
    assert lib.lookup(tmp_path, bad) is None


def test_dry_run_computes_nothing(monkeypatch, tmp_path, capsys):
    calls = []
    rc = _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi", "--dry-run"])
    assert rc == 0 and calls == []
    assert "3 to run" in capsys.readouterr().out


def test_unmodelled_type_request_is_refused_with_the_reason(monkeypatch, tmp_path, capsys):
    calls = []
    _run_batch(monkeypatch, tmp_path, calls,
               ["--scenario", "tehri_bhagirathi", "--type", "overtopping"])
    assert calls == []
    assert "Not modelled distinctly" in capsys.readouterr().out


def test_force_moves_the_previous_run_aside(monkeypatch, tmp_path):
    calls = []
    _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi", "--limit", "1"])
    run = tmp_path / "runs" / "lib_tehri_bhagirathi__complete_dam_break__frl"
    (run / "life_loss_w0_vague.json").write_text("{}")  # a derived cache of the old run
    _run_batch(monkeypatch, tmp_path, calls,
               ["--scenario", "tehri_bhagirathi", "--limit", "1", "--force"])
    assert not (run / "life_loss_w0_vague.json").exists()
    moved = list((tmp_path / "runs" / ".superseded").iterdir())
    assert len(moved) == 1 and (moved[0] / "life_loss_w0_vague.json").exists()


def test_preset_at_another_resolution(tehri):
    presets = list(lib.iter_presets(tehri, resolution_m=60.0))
    assert [p.key for p in presets][0] == "tehri_bhagirathi__complete_dam_break__frl__r60"
    assert all(p.resolution_m == 60.0 for p in presets)
    s = lib.build_preset_scenario(tehri, "complete_dam_break", "frl", 60.0)
    assert s.domain.resolution_m == 60.0 and s.id == tehri.id
    entry = lib.entry_for(presets[0], duration_hours=6.0, completed_utc=None,
                          wall_seconds=None, status="failed")
    assert entry["resolution_m"] == 60.0
    assert lib.run_meta_for(presets[0])["library_resolution_m"] == 60.0


def test_precompute_at_60_m_runs_separate_presets(monkeypatch, tmp_path):
    calls = []
    _run_batch(monkeypatch, tmp_path, calls, ["--scenario", "tehri_bhagirathi", "--limit", "1"])
    _run_batch(monkeypatch, tmp_path, calls,
               ["--scenario", "tehri_bhagirathi", "--resolution", "60", "--limit", "1"])
    assert [c[0] for c in calls] == [
        "lib_tehri_bhagirathi__complete_dam_break__frl",
        "lib_tehri_bhagirathi__complete_dam_break__frl__r60",
    ]
    assert calls[1][2] == 60.0
