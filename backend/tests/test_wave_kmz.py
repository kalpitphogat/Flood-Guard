"""Time-animated KMZ of the instantaneous wet extent."""

from __future__ import annotations

import re
import zipfile

import numpy as np
from rasterio.transform import from_origin

from floodguard.postprocess.exports import write_wave_animation_kmz

T = from_origin(300000, 3300000, 100.0, 100.0)


def _frames():
    a = np.zeros((6, 6))
    a[2:4, 0:2] = 1.0
    b = np.zeros((6, 6))
    b[2:4, 0:5] = 2.0
    dry = np.zeros((6, 6))
    return [(0.0, dry), (300.0, a), (600.0, b), (900.0, dry)]


def test_one_placemark_per_wet_frame_with_contiguous_spans(tmp_path):
    out = write_wave_animation_kmz(_frames(), T, "EPSG:32644", tmp_path / "w.kmz", name="t")
    assert out is not None and out.feature_count == 2
    kml = zipfile.ZipFile(out.path).read("doc.kml").decode()
    spans = re.findall(r"<begin>(.*?)</begin><end>(.*?)</end>", kml)
    assert spans == [
        ("2024-01-01T00:05:00Z", "2024-01-01T00:10:00Z"),  # lasts until the next frame
        ("2024-01-01T00:10:00Z", "2024-01-01T00:15:00Z"),
    ]
    assert "nominal anchor" in kml  # the calendar date is not presented as a forecast
    lon = float(re.search(r"<coordinates>([-\d.]+),", kml).group(1))
    assert 60 < lon < 100  # reprojected to WGS84 degrees, not UTM metres


def test_no_wet_frame_writes_nothing(tmp_path):
    dry = [(0.0, np.zeros((3, 3))), (60.0, np.zeros((3, 3)))]
    assert write_wave_animation_kmz(dry, T, "EPSG:32644", tmp_path / "w.kmz", name="t") is None
    assert not (tmp_path / "w.kmz").exists()
