"""Static inundation KML: unknown values must not crash the export or print as "nan"."""

from __future__ import annotations

import re

import geopandas as gpd
from shapely.geometry import box

from floodguard.postprocess.exports import write_kml


def _gdf(arrivals):
    return gpd.GeoDataFrame(
        {
            "depth_band_label": ["0.5-1.5 m"] * len(arrivals),
            "arrival_time_min": arrivals,
        },
        geometry=[box(300000 + 200 * i, 3300000, 300100 + 200 * i, 3300100) for i in range(len(arrivals))],
        crs="EPSG:32644",
    )


def test_unknown_arrival_is_written_without_a_time_span(tmp_path):
    # A polygon whose arrival is unknown comes out of the dataframe as NaN, not None.
    out = write_kml(_gdf([30.0, float("nan")]), tmp_path / "f.kml", {"run": "t"})
    kml = out.path.read_text(encoding="utf-8")
    assert out.feature_count == 2
    assert kml.count("<TimeSpan>") == 1  # only the polygon with a known arrival
    assert "<begin>2024-01-01T00:30:00Z</begin>" in kml
    assert "arrival unknown" in kml
    assert re.search(r"\bnan\b", kml, re.IGNORECASE) is None
