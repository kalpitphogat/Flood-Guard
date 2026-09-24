"""The P1 features: uploads, share links, Demo Mode listing, animated tiles, 3D, AOI.

Each is tested against a synthetic completed run written to a temporary data
directory, so the tests exercise exactly the files a real `floodguard
simulate` leaves behind — and each is tested for its refusal paths as
carefully as its happy path.
"""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

ORIGIN = (320000.0, 3350000.0)  # UTM 44N, roughly Tehri
CELL = 90.0
SHAPE = (40, 60)
CRS = "EPSG:32644"


def _write_tif(path, array, nodata=-9999.0):
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype="float32", crs=CRS, transform=from_origin(*ORIGIN, CELL, CELL), nodata=nodata,
    ) as dst:
        dst.write(array.astype("float32"), 1)


def _make_run(data_dir, run_id="run_test"):
    run = data_dir / "runs" / run_id
    run.mkdir(parents=True)
    rows, cols = SHAPE
    yy, xx = np.mgrid[0:rows, 0:cols]
    depth_a = np.where(np.abs(yy - rows // 2) < 6, 8.0 - 0.1 * xx, 0.0).clip(0)
    depth_b = np.where(np.abs(yy - rows // 2) < 5, 7.5 - 0.1 * xx, 0.0).clip(0)
    velocity = np.where(depth_a > 0, 3.0, 0.0)
    arrival = np.where(depth_a > 0.3, 60.0 * xx, -1.0)
    bed = 500.0 - 2.0 * xx + 3.0 * np.abs(yy - rows // 2)

    for suffix, depth in (("", depth_a), ("_swe_fv", depth_a), ("_sph_swe", depth_b)):
        _write_tif(run / f"max_depth{suffix}.tif", depth)
        _write_tif(run / f"max_velocity{suffix}.tif", velocity)
        _write_tif(run / f"arrival_time{suffix}.tif", arrival)
        _write_tif(run / f"max_hazard{suffix}.tif", depth * velocity)
    _write_tif(run / "bed.tif", bed)
    np.savez_compressed(
        run / "frames_swe_fv.npz",
        times_s=np.array([300.0, 600.0]),
        f0000=(depth_a * 0.5).astype(np.float32),
        f0001=depth_a.astype(np.float32),
    )

    def engine(eid, name, depth):
        return {
            "requested_engine": eid, "actual_engine": eid, "display_name": name,
            "is_real_solver": True, "substituted": False, "substitution_reason": "",
            "honesty_note": f"Computed with {name}.", "error": None,
            "summary": {
                "flooded_area_km2": float((depth >= 0.3).sum() * CELL**2 / 1e6),
                "max_depth_m": float(depth.max()), "max_velocity_ms": 3.0,
                "earliest_arrival_min": 0.0, "max_hazard_m2s": float(depth.max() * 3),
                "runtime_s": 1.0, "steps": 10, "mass_error": 0.0, "warnings": [],
            },
        }

    result = {
        "scenario_id": "tehri_bhagirathi", "run_id": run_id, "out_dir": str(run),
        "runtime_s": 2.0, "resolution_m": CELL, "crs": CRS,
        "completed_utc": "2026-09-25T00:00:00Z",
        "breach": {"used": _prediction(), "predictions": [_prediction()],
                   "spread": {"width_m": {"spread_ratio": 1.0, "min": 1, "max": 1}}},
        "hydrograph": {"peak_discharge_m3s": 1000.0, "time_to_peak_s": 600.0,
                       "total_volume_m3": 1e7, "mass_error": 0.0, "provenance": {}},
        "engines": [
            engine("swe_fv", "FloodGuard-SWE (Delft3D-class FV solver)", depth_a),
            engine("sph_swe", "FloodGuard-SPH (depth-integrated SWE-SPH)", depth_b),
        ],
        "hazard": {}, "towns": [], "towns_by_engine": {"swe_fv": [], "sph_swe": []},
        "impact": None, "exports": [], "warnings": [],
    }
    (run / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return run_id


def _prediction():
    return {"model": "Froehlich (2008)", "width_m": 100.0, "depth_m": 50.0, "side_slope": 1.0,
            "formation_time_min": 30.0, "reference": "Froehlich 2008", "applicable": True,
            "caveats": []}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.api import results, views
    from app.core import config

    monkeypatch.setenv("FLOODGUARD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    results._layer.cache_clear()
    views._scene.cache_clear()
    from app.main import app

    _make_run(tmp_path)
    yield TestClient(app)
    config.get_settings.cache_clear()
    results._layer.cache_clear()
    views._scene.cache_clear()


# --- summary honesty ----------------------------------------------------------------


def test_summary_reports_the_real_resolution_never_zero(client):
    body = client.get("/api/results/run_test/summary").json()
    assert body["resolution_m"] == pytest.approx(CELL)


# --- Demo Mode ---------------------------------------------------------------------


def test_runs_listing_offers_completed_runs_only(client, tmp_path):
    (tmp_path / "runs" / "half_finished").mkdir()
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == ["run_test"]
    assert runs[0]["engine_count"] == 2
    assert runs[0]["has_frames"] is True


# --- comparison -------------------------------------------------------------------


def test_comparison_populates_from_two_engines_and_writes_a_difference(client, tmp_path):
    body = client.get("/api/results/run_test/comparison").json()
    assert body["rows"], body["note"]
    assert 0.0 < body["critical_success_index"] < 1.0
    assert body["extent_rmse_m"] > 0.0
    assert (tmp_path / "runs" / "run_test" / "depth_difference.tif").exists()


# --- tiles and frames -------------------------------------------------------------


def _tile_of(lon, lat, z=11):
    import math

    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, x, y


def _domain_centre():
    from pyproj import Transformer

    x = ORIGIN[0] + SHAPE[1] * CELL / 2
    y = ORIGIN[1] - SHAPE[0] * CELL / 2
    return Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(x, y)


@pytest.mark.parametrize("layer", ["depth", "velocity", "arrival", "hazard", "difference"])
def test_every_layer_tiles(client, layer):
    from PIL import Image

    z, x, y = _tile_of(*_domain_centre())
    r = client.get(f"/api/results/run_test/tiles/{z}/{x}/{y}.png?layer={layer}")
    assert r.status_code == 200, r.text
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (256, 256)
    if layer != "difference":
        assert np.asarray(img)[..., 3].max() > 0, "the flooded valley should be drawn"


def test_frames_are_listed_and_a_frame_tiles_differently_from_the_max(client):
    frames = client.get("/api/results/run_test/frames").json()
    assert frames["engines"]["swe_fv"] == [300.0, 600.0]
    z, x, y = _tile_of(*_domain_centre())
    first = client.get(f"/api/results/run_test/tiles/{z}/{x}/{y}.png?frame=0&engine=swe_fv")
    maxed = client.get(f"/api/results/run_test/tiles/{z}/{x}/{y}.png")
    assert first.status_code == 200
    assert first.content != maxed.content


def test_a_missing_frame_is_a_404_not_an_empty_tile(client):
    r = client.get("/api/results/run_test/tiles/11/1000/800.png?frame=99&engine=swe_fv")
    assert r.status_code == 404


def test_an_engine_that_did_not_run_is_a_404(client):
    r = client.get("/api/results/run_test/tiles/11/1000/800.png?engine=anuga")
    assert r.status_code == 404


def test_legend_matches_the_layer(client):
    bins = client.get("/api/results/run_test/legend?layer=hazard").json()["bins"]
    assert [b["label"].split(":")[0] for b in bins] == ["H1", "H2", "H3", "H4", "H5", "H6"]


# --- share links -----------------------------------------------------------------


def test_share_link_roundtrip(client):
    created = client.post(
        "/api/results/run_test/share", json={"view": {"layer": "hazard", "evil": "x"}}
    ).json()
    assert len(created["code"]) == 8 and created["path"] == f"/s/{created['code']}"
    resolved = client.get(f"/api/share/{created['code']}").json()
    assert resolved["run_id"] == "run_test"
    assert resolved["view"] == {"layer": "hazard"}, "unknown view keys must be dropped"


def test_share_refuses_an_unknown_run_and_code(client):
    assert client.post("/api/results/nope/share", json={}).status_code == 404
    assert client.get("/api/share/zzzzzzzz").status_code == 404


# --- 3D ----------------------------------------------------------------------------


def test_3d_scene_is_lon_lat_and_terrarium_decodes_to_the_bed(client):
    from PIL import Image

    meta = client.get("/api/results/run_test/3d/meta").json()
    w, s, e, n = meta["bounds"]
    assert 77 < w < e < 80 and 29 < s < n < 31
    assert meta["max_depth_m"] == pytest.approx(8.0, abs=0.5)

    png = client.get("/api/results/run_test/3d/terrain.png").content
    rgb = np.asarray(Image.open(io.BytesIO(png))).astype(np.float64)
    elev = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    valid = elev > 0
    assert elev[valid].min() >= meta["bed_min_m"] - 1
    assert elev[valid].max() <= meta["bed_max_m"] + 1

    tex = np.asarray(Image.open(io.BytesIO(client.get("/api/results/run_test/3d/water-texture.png").content)))
    assert (tex[..., 3] == 0).any() and (tex[..., 3] > 0).any(), "dry must be transparent"


# --- uploads ---------------------------------------------------------------------


def _dem_bytes(crs=CRS, scale=1.0):
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    data = (np.linspace(300, 900, 50 * 50).reshape(50, 50) * scale).astype("float32")
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", height=50, width=50, count=1, dtype="float32",
                      crs=crs, transform=from_origin(*ORIGIN, 30, 30)) as dst:
            dst.write(data, 1)
        return mem.read()


def test_a_valid_dem_is_accepted_with_its_metadata(client):
    r = client.post("/api/uploads/dem", files={"file": ("dem.tif", _dem_bytes())})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["crs"] == CRS
    assert meta["resolution_m"] == pytest.approx(30.0)
    assert len(meta["sha256"]) == 64
    assert client.get("/api/uploads?kind=dem").json()[0]["id"] == meta["id"]


def test_a_dem_without_a_crs_is_refused(client):
    r = client.post("/api/uploads/dem", files={"file": ("dem.tif", _dem_bytes(crs=None))})
    assert r.status_code == 422
    assert any("coordinate reference system" in i for i in r.json()["detail"]["issues"])


def test_a_dem_in_centimetres_is_refused(client):
    r = client.post("/api/uploads/dem", files={"file": ("dem.tif", _dem_bytes(scale=100.0))})
    assert r.status_code == 422
    assert any("centimetres" in i for i in r.json()["detail"]["issues"])


def test_wrong_extension_is_refused(client):
    r = client.post("/api/uploads/dem", files={"file": ("dem.png", b"x")})
    assert r.status_code == 422


HYDRO_OK = "time_min,discharge_m3s\n0,0\n10,5000\n30,12000\n60,3000\n120,0\n"


def test_a_hydrograph_is_accepted_and_summarised(client):
    r = client.post("/api/uploads/hydrograph", files={"file": ("q.csv", HYDRO_OK.encode())})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["peak_discharge_m3s"] == 12000
    assert meta["time_to_peak_min"] == 30
    assert meta["duration_hours"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    "body, reason",
    [
        ("time,discharge_m3s\n0,0\n1,5\n", "declare its unit"),
        ("time_s,discharge_cfs\n0,0\n1,5\n", "imperial"),
        ("time_s,discharge_m3s\n0,0\n0,5\n", "strictly increasing"),
        ("time_s,discharge_m3s\n0,0\n5,-3\n", "non-negative"),
    ],
)
def test_a_bad_hydrograph_is_refused_with_the_reason(client, body, reason):
    r = client.post("/api/uploads/hydrograph", files={"file": ("q.csv", body.encode())})
    assert r.status_code == 422
    assert reason in " ".join(r.json()["detail"]["issues"])


def _aoi_geojson(lon, lat, d=0.01):
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d],
            [lon - d, lat - d]]
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    ]}).encode()


def test_aoi_stats_inside_the_flood(client):
    lon, lat = _domain_centre()
    up = client.post("/api/uploads/aoi", files={"file": ("d.geojson", _aoi_geojson(lon, lat))}).json()
    stats = client.get(f"/api/results/run_test/aoi-stats?upload_id={up['id']}").json()
    assert stats["flooded_area_km2"] > 0
    assert stats["max_depth_m"] > 0


def test_aoi_outside_the_domain_is_not_covered_not_zero(client):
    up = client.post("/api/uploads/aoi", files={"file": ("far.geojson", _aoi_geojson(85.0, 21.0))}).json()
    stats = client.get(f"/api/results/run_test/aoi-stats?upload_id={up['id']}").json()
    assert stats["flooded_area_km2"] is None
    assert "not the same as 'no flooding'" in stats["reason"]


def test_an_aoi_of_points_is_refused(client):
    pts = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [78, 30]}}
    ]}).encode()
    r = client.post("/api/uploads/aoi", files={"file": ("p.geojson", pts)})
    assert r.status_code == 422


# --- user hydrograph in the pipeline --------------------------------------------------


def test_user_hydrograph_becomes_the_inflow_and_says_so(tmp_path):
    from floodguard.pipeline import load_user_hydrograph

    path = tmp_path / "q.csv"
    path.write_text(HYDRO_OK, encoding="utf-8")
    hyd = load_user_hydrograph(path)
    assert hyd.peak_discharge_m3s == 12000
    assert hyd.q_at(30 * 60) == pytest.approx(12000)
    assert np.isnan(hyd.water_level_m).all(), "level was not modelled, so it is NaN, not 0"
    assert "SUPPLIED" in hyd.warnings[0]
    assert hyd.provenance["breach_model"] == "user-supplied hydrograph"
