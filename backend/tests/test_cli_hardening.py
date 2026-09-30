"""Bad CLI input fails at once with one readable line, never a deep traceback."""

from __future__ import annotations

import pytest

from floodguard import cli
from floodguard import library as lib


def _run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["simulate", "--scenario", "tehri_bhagirathi", "--resolution", "0"],
    ["simulate", "--scenario", "tehri_bhagirathi", "--resolution", "-30"],
    ["simulate", "--scenario", "tehri_bhagirathi", "--resolution", "nan"],
    ["simulate", "--scenario", "tehri_bhagirathi", "--duration", "abc"],
    ["precompute", "--scenario", "tehri_bhagirathi", "--limit", "0"],
    ["precompute", "--scenario", "tehri_bhagirathi", "--type", "piping"],
    ["life-loss", "--runs", "x", "--warning-min", "99999"],
    ["demo", "--api-port", "70000", "--check"],
])
def test_bad_flags_are_rejected_by_the_parser(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_an_unknown_scenario_is_one_line(capsys):
    code, err = _run(["preprocess", "--scenario", "no_such_dam"], capsys)
    assert code == 2 and "not found" in err and "Traceback" not in err


def test_an_invalid_scenario_names_the_field(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\nname: x\nscenario_type: complete_dam_break\n"
                   "dam: {id: d, name: d, river: r, state: s, lon: 500, lat: 30, "
                   "dam_type: earthfill, structural_height_m: 10}\n")
    code, err = _run(["preprocess", "--scenario", str(bad)], capsys)
    assert code == 2 and "dam.lon" in err


def test_broken_yaml_is_reported_as_such(tmp_path, capsys):
    bad = tmp_path / "broken.yaml"
    bad.write_text("id: [unclosed\n")
    code, err = _run(["preprocess", "--scenario", str(bad)], capsys)
    assert code == 2 and "not valid YAML" in err


def test_precompute_refuses_a_resolution_the_library_never_offers(capsys):
    code, err = _run(["precompute", "--scenario", "tehri_bhagirathi", "--resolution", "90",
                      "--dry-run"], capsys)
    assert code == 2 and "preset library holds" in err


def test_unknown_engine_is_named(capsys, monkeypatch):
    code, err = _run(["simulate", "--scenario", "tehri_bhagirathi", "--engines", "swe_fv,delft4d"],
                     capsys)
    assert code == 2 and "delft4d" in err


def test_a_file_given_as_data_dir_is_rejected(tmp_path, capsys):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(SystemExit):
        cli.main(["verify", "--data-dir", str(f)])
    assert "not a directory" in capsys.readouterr().err


def test_precompute_type_choices_match_the_library():
    assert set(cli._PRESET_TYPE_CHOICES) == set(lib.PRESET_TYPES)
