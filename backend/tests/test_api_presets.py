"""Preset API: listing, instant precomputed results, quick-estimate mode.

No solver runs here. Precomputed runs are fake result.json files in a temp
data dir, and the job runner is replaced so a quick job is inspected, not solved.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from floodguard import library as lib

REPO = Path(__file__).resolve().parents[2]
KEY = "tehri_bhagirathi__complete_dam_break__frl"


class _FakeRunner:
    def __init__(self):
        self.submitted = []

    def submit(self, job_id, scenario, run_meta=None):
        self.submitted.append((job_id, scenario, run_meta))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.api import simulate
    from app.core import config
    from app.core.jobs import JobStore

    shutil.copytree(REPO / "data" / "scenarios", tmp_path / "scenarios")
    shutil.copytree(REPO / "data" / "catalog", tmp_path / "catalog")
    monkeypatch.setenv("FLOODGUARD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()

    runner = _FakeRunner()
    store = JobStore(tmp_path / "jobs.sqlite")
    monkeypatch.setattr(simulate, "get_runner", lambda: runner)
    monkeypatch.setattr(simulate, "get_store", lambda: store)

    from app.main import app

    yield TestClient(app), tmp_path, runner
    config.get_settings.cache_clear()


def _precompute(data_dir: Path, key: str = KEY) -> None:
    """A finished library run, as `floodguard precompute` leaves it."""
    scenario_id, stype, level, _res = lib.parse_key(key)
    result = lib.result_path(data_dir, key)
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({
        "run_id": lib.run_id_for(key), "scenario_id": scenario_id,
        "completed_utc": "2026-09-30T05:00:00Z", "run_mode": "precomputed",
        "run_meta": {"run_mode": "precomputed", "library_key": key},
        "resolution_m": 120.0, "engines": [],
    }))
    lib.record(data_dir, key, {
        "run_id": lib.run_id_for(key), "scenario_id": scenario_id, "scenario_type": stype,
        "level": level, "level_m": 830.0, "resolution_m": 120.0, "duration_hours": 6.0,
        "completed_utc": "2026-09-30T05:00:00Z", "wall_seconds": 210.0,
        "status": "succeeded", "error": None,
    })


def test_presets_lists_every_combination_with_availability(env):
    client, data_dir, _ = env
    _precompute(data_dir)
    body = client.get("/api/presets").json()

    assert body["resolution_m"] == 120.0
    assert body["engines"] == ["swe_fv"]
    assert body["quick"] == {"resolution_m": 200.0, "duration_hours": 1.0,
                             "engines": ["swe_fv"], "label": lib.QUICK_LABEL}
    dams = {d["scenario_id"]: d for d in body["dams"]}
    assert [lv["level_m"] for lv in dams["tehri_bhagirathi"]["levels"]] == [830.0, 785.0, 740.0]

    presets = {p["key"]: p for p in body["presets"]}
    assert len(presets) == 36  # 2 dams x 3 types x 3 levels x 2 resolutions, all listed
    assert body["resolutions"] == [120.0, 60.0]
    assert presets["tehri_bhagirathi__complete_dam_break__frl__r60"]["available"] is False
    assert presets["tehri_bhagirathi__complete_dam_break__frl__r60"]["resolution_m"] == 60.0
    assert presets[KEY]["available"] is True
    assert presets[KEY]["completed_utc"] == "2026-09-30T05:00:00Z"
    mid = presets["tehri_bhagirathi__complete_dam_break__mid"]
    assert mid["available"] is False and mid["reason"] == "Not precomputed yet."
    over = presets["tehri_bhagirathi__overtopping__frl"]
    assert over["modelled"] is False and over["available"] is False
    assert "Not modelled distinctly" in over["reason"]


def test_preset_submit_returns_the_stored_run_immediately(env):
    client, data_dir, runner = env
    _precompute(data_dir)
    r = client.post("/api/simulate", json={"scenario_id": "tehri_bhagirathi", "preset_key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "precomputed"
    assert body["run_id"] == f"lib_{KEY}"
    assert body["status"] == "succeeded"
    assert body["mode_label"] == "Precomputed on 2026-09-30 · 120 m"
    assert runner.submitted == []  # no solver was queued

    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "succeeded"


def test_unknown_preset_is_404(env):
    client, _, _ = env
    r = client.post("/api/simulate", json={"preset_key": "tehri_bhagirathi__complete_dam_break__x"})
    assert r.status_code == 404
    r = client.post("/api/simulate", json={"preset_key": "nonsense"})
    assert r.status_code == 404


def test_not_yet_computed_preset_is_409_and_never_falls_back(env):
    client, data_dir, runner = env
    _precompute(data_dir)  # frl exists; mid does not
    r = client.post("/api/simulate",
                    json={"preset_key": "tehri_bhagirathi__complete_dam_break__mid"})
    assert r.status_code == 409
    assert "not been precomputed" in r.json()["detail"]
    assert runner.submitted == []


def test_unmodelled_preset_is_409_with_the_reason(env):
    client, _, _ = env
    r = client.post("/api/simulate", json={"preset_key": "tehri_bhagirathi__overtopping__frl"})
    assert r.status_code == 409
    assert "Not modelled distinctly" in r.json()["detail"]


def test_preset_for_the_wrong_dam_is_rejected(env):
    client, data_dir, _ = env
    _precompute(data_dir)
    r = client.post("/api/simulate", json={"scenario_id": "hirakud_mahanadi", "preset_key": KEY})
    assert r.status_code == 422


def test_quick_mode_forces_the_quick_settings(env):
    client, _, runner = env
    r = client.post("/api/simulate", json={
        "scenario_id": "hirakud_mahanadi", "quick": True,
        "resolution_m": 30, "duration_hours": 24, "engines": ["swe_fv", "sph_swe"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "quick_estimate"
    assert body["mode_label"] == lib.QUICK_LABEL
    assert body["run_id"] is None

    (_job_id, scenario, run_meta), = runner.submitted
    assert scenario.domain.resolution_m == 200.0
    assert scenario.solver.duration_hours == 1.0
    assert scenario.engines == ["swe_fv"]
    assert run_meta["run_mode"] == "quick_estimate"


def test_full_mode_is_unchanged(env):
    client, _, runner = env
    r = client.post("/api/simulate", json={
        "scenario_id": "tehri_bhagirathi", "resolution_m": 90, "engines": ["swe_fv"],
    })
    assert r.status_code == 200
    assert r.json()["mode"] == "full"
    (_job_id, scenario, run_meta), = runner.submitted
    assert scenario.domain.resolution_m == 90.0
    assert run_meta is None


def test_runs_listing_carries_the_run_mode(env):
    client, data_dir, _ = env
    _precompute(data_dir)
    runs = client.get("/api/runs").json()
    assert runs[0]["run_mode"] == "precomputed"
    assert runs[0]["library_key"] == KEY


def test_life_loss_endpoint_reports_not_computed_without_population(env):
    client, data_dir, _ = env
    _precompute(data_dir)
    body = client.get(f"/api/results/lib_{KEY}/life-loss").json()
    assert body["computed"] is False
    assert "population" in body["reason"].lower()
    assert body["caveats"]


def test_datasets_groups_the_manifest_by_source(env):
    client, data_dir, _ = env
    body = client.get("/api/datasets").json()
    assert body["sources"] == [] and "data pack" in body["note"]
    (data_dir / "MANIFEST.json").write_text(json.dumps({"entry_count": 3, "entries": [
        {"source": "Copernicus", "licence": "CC", "size_bytes": 10, "url": "u1"},
        {"source": "Copernicus", "licence": "CC", "size_bytes": 5, "url": "u2"},
        {"source": "WorldPop", "licence": "CC BY 4.0", "size_bytes": 7, "url": "u3"},
    ]}))
    body = client.get("/api/datasets").json()
    by = {s["source"]: s for s in body["sources"]}
    assert by["Copernicus"]["files"] == 2 and by["Copernicus"]["total_bytes"] == 15
    assert by["WorldPop"]["licences"] == ["CC BY 4.0"]


def test_cached_life_loss_is_served_only_for_the_run_it_was_computed_from(env):
    client, data_dir, _ = env
    _precompute(data_dir)
    run = data_dir / "runs" / f"lib_{KEY}"
    cached = {"method": "Graham", "citation": "c", "computed": True, "caveats": ["x"],
              "range": [1, 2], "estimate": 1, "population_at_risk": 10,
              "run_completed_utc": "2026-09-30T05:00:00Z"}
    (run / "life_loss_w0_vague.json").write_text(json.dumps(cached))
    assert client.get(f"/api/results/lib_{KEY}/life-loss").json()["computed"] is True
    cached["run_completed_utc"] = "2020-01-01T00:00:00Z"  # from an older run
    (run / "life_loss_w0_vague.json").write_text(json.dumps(cached))
    body = client.get(f"/api/results/lib_{KEY}/life-loss").json()
    assert body["computed"] is False  # recomputed; no population here, so honestly not computed


def test_a_60_m_preset_is_served_with_its_resolution(env):
    client, data_dir, _ = env
    key60 = "tehri_bhagirathi__complete_dam_break__frl__r60"
    _precompute(data_dir, key60)
    r = client.post("/api/simulate", json={"preset_key": key60}).json()
    assert r["run_id"] == f"lib_{key60}" and r["mode_label"].endswith("60 m")


def test_dam_display_names_keep_acronyms():
    from app.api.presets import display_name

    assert display_name("TEHRI HPP") == "Tehri HPP"
    assert display_name("HIRAKUD") == "Hirakud"
    assert display_name("NTPC DAM") == "NTPC Dam"
