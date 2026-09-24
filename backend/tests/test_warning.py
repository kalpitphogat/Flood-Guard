"""Early warning: alert levels, safe ground, bulletin text, SMS and CAP 1.2."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from floodguard.warning.bulletin import (
    CAP_NS,
    build,
    cap_xml,
    classify_town,
)
from floodguard.warning.safe_ground import compass, nearest_safe_ground, safe_mask


def town(**kw):
    base = dict(name="Devprayag", lon=78.6, lat=30.15, population=2152, in_domain=True,
                arrival_min=30.0, max_depth_m=8.0, max_velocity_ms=4.0)
    base.update(kw)
    return base


# --- alert levels ------------------------------------------------------------------


def test_deep_fast_early_is_red():
    assert classify_town(town()).level == "RED"


def test_deep_but_late_is_orange_not_red():
    assert classify_town(town(arrival_min=300.0)).level == "ORANGE"


def test_shallow_slow_is_yellow():
    assert classify_town(town(max_depth_m=0.35, max_velocity_ms=0.2, arrival_min=400)).level == "YELLOW"


def test_dry_town_is_none_and_outside_is_not_assessed():
    assert classify_town(town(max_depth_m=0.0, arrival_min=None)).level == "NONE"
    assert classify_town(town(in_domain=False)).level == "NOT_ASSESSED"


def test_unknown_depth_is_never_treated_as_safe_flooding():
    alert = classify_town(town(max_depth_m=None, max_velocity_ms=None, arrival_min=None))
    assert alert.level == "NONE" and alert.hazard_class is None


# --- safe ground --------------------------------------------------------------------


def _valley(rows=40, cols=40, cell=90.0):
    from rasterio.transform import from_origin

    yy, xx = np.mgrid[0:rows, 0:cols]
    bed = 500.0 + 4.0 * np.abs(xx - cols // 2)          # a V valley, running north-south
    depth = np.where(np.abs(xx - cols // 2) <= 3, 10.0, 0.0)
    return bed, depth, from_origin(320000.0, 3350000.0, cell, cell)


def test_safe_ground_is_dry_and_above_the_flood_with_freeboard():
    bed, depth, _ = _valley()
    safe, surface = safe_mask(depth, bed, freeboard_m=2.0)
    assert not (safe & (depth >= 0.3)).any()
    assert np.all(bed[safe] >= surface[safe] + 2.0)
    # The flood surface is 500 + 12 + 10 = 522 at the edge; ground at 504-516 near
    # the channel is dry but NOT safe.
    cols = np.nonzero(safe[20])[0]
    assert np.all(np.abs(cols - 20) >= 6)


def test_nearest_safe_ground_points_across_the_valley():
    from pyproj import Transformer
    from rasterio.transform import xy

    bed, depth, transform = _valley()
    x, y = xy(transform, 20, 20)
    lon, lat = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True).transform(x, y)
    [(sg, reason)] = nearest_safe_ground(depth, bed, transform, "EPSG:32644", [(lon, lat)])
    assert sg is not None, reason
    assert sg.direction in ("E", "W")
    assert sg.height_above_flood_m >= 2.0
    assert 0.3 < sg.distance_km < 1.0


def test_no_flood_means_no_target_with_a_reason():
    bed, _, transform = _valley()
    [(sg, reason)] = nearest_safe_ground(np.zeros_like(bed), bed, transform, "EPSG:32644", [(78.0, 30.0)])
    assert sg is None and "nothing flooded" in reason


def test_compass():
    assert [compass(b) for b in (0, 44, 46, 90, 180, 270, 359)] == ["N", "NE", "NE", "E", "S", "W", "N"]


# --- bulletin, SMS and CAP -------------------------------------------------------------


@pytest.fixture()
def payload():
    run = {"run_id": "r1", "towns": [
        town(),
        town(name="Rishikesh", arrival_min=95.0, max_depth_m=0.8, max_velocity_ms=0.6),
        town(name="Haridwar", in_domain=False, arrival_min=None, max_depth_m=None, max_velocity_ms=None),
    ]}
    return build(run, scenario_name="Tehri test")


def test_bulletin_orders_by_severity_then_lead_time(payload):
    assert [t["level"] for t in payload["towns"]] == ["RED", "ORANGE", "NOT_ASSESSED"]
    assert payload["counts"]["RED"] == 1


def test_bulletin_states_its_convention_and_that_it_is_not_official(payload):
    assert "NOT AN OFFICIAL WARNING" in payload["text_en"]
    assert "आधिकारिक चेतावनी नहीं" in payload["text_hi"]
    assert "convention" in payload["convention"].lower()


def test_population_total_is_null_if_any_part_is_unknown():
    run = {"run_id": "r", "towns": [town(), town(name="X", population=None)]}
    assert build(run, scenario_name="s")["population_red_orange"] is None


def test_sms_reports_its_segments(payload):
    for msg in payload["sms"]:
        assert msg["text"].startswith("EXERCISE")
        assert msg["segments"] == -(-msg["chars"] // 160)
    for msg in payload["sms_hi"]:
        assert msg["segments"] == -(-msg["chars"] // 70)


def test_cap_is_well_formed_and_never_actual(payload):
    root = ET.fromstring(cap_xml(payload).split("\n", 1)[1])
    ns = {"c": CAP_NS}
    assert root.find("c:status", ns).text == "Exercise"
    infos = root.findall("c:info", ns)
    assert {i.find("c:language", ns).text for i in infos} == {"en-IN", "hi-IN"}
    assert all(i.find("c:certainty", ns).text == "Possible" for i in infos)
    red = [i for i in infos if i.find("c:severity", ns).text == "Extreme"]
    assert red and red[0].find("c:area/c:areaDesc", ns).text == "Devprayag"
    with pytest.raises(ValueError, match="refused"):
        cap_xml(payload, status="Actual")


# --- API -------------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.api import results, views, warning
    from app.core import config
    from tests.test_api_views import _make_run

    monkeypatch.setenv("FLOODGUARD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    for cache in (results._layer, views._scene, warning._bulletin):
        cache.cache_clear()
    _make_run(tmp_path)
    path = tmp_path / "runs" / "run_test" / "result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    from pyproj import Transformer

    lon, lat = Transformer.from_crs("EPSG:32644", "EPSG:4326", always_xy=True).transform(
        320000.0 + 30 * 90.0, 3350000.0 - 20 * 90.0
    )
    data["towns"] = [town(name="Centre", lon=lon, lat=lat)]
    path.write_text(json.dumps(data), encoding="utf-8")
    from app.main import app

    yield TestClient(app)
    config.get_settings.cache_clear()
    warning._bulletin.cache_clear()


def test_warning_endpoint_and_downloads(client):
    body = client.get("/api/results/run_test/warning").json()
    assert body["towns"][0]["level"] == "RED"
    assert body["towns"][0]["safe_ground"] is not None
    hi = client.get("/api/results/run_test/warning/bulletin.txt?lang=hi")
    assert hi.status_code == 200 and "चेतावनी" in hi.text
    cap = client.get("/api/results/run_test/warning/cap.xml")
    assert cap.status_code == 200 and CAP_NS in cap.text
    assert client.get("/api/results/run_test/warning/cap.xml?status=Actual").status_code == 422


def test_breach_ensemble_404s_with_a_reason_when_absent(client):
    r = client.get("/api/results/run_test/breach-ensemble")
    assert r.status_code == 404 and "user-supplied" in r.json()["detail"]
