"""A missing OSM name (NaN in a GeoDataFrame) must never become the settlement "nan"."""

from __future__ import annotations

import math

from floodguard.impact.exposure import labelled_facilities, named_evacuation_rows, osm_name


def test_missing_names_are_none():
    for missing in (None, math.nan, float("nan"), "", "  ", "nan", "NaN"):
        assert osm_name(missing) is None, missing
    assert osm_name(" Koteshwar ") == "Koteshwar"
    assert osm_name("Nangal") == "Nangal"  # names that merely start with "nan" survive


def test_stored_rows_without_a_name_are_dropped():
    rows = [
        {"name": "nan", "arrival_min": 17.5},
        {"name": "Naramghat", "arrival_min": 30.0},
        {"name": None, "arrival_min": 40.0},
    ]
    assert [r["name"] for r in named_evacuation_rows(rows)] == ["Naramghat"]


def test_stored_facilities_without_a_name_get_a_label():
    rows = [
        {"kind": "healthcare", "name": math.nan, "amenity": "clinic"},
        {"kind": "education", "name": None, "amenity": None},
        {"kind": "emergency", "name": "Laxman Jhula police station", "amenity": "police"},
    ]
    assert [r["name"] for r in labelled_facilities(rows)] == [
        "unnamed clinic",
        "unnamed education",
        "Laxman Jhula police station",
    ]
