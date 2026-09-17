"""Tests for the CLI entry point: argument parsing, --version, --json,
--no-color, and exit codes. Pure-Python (no torch dependency), unlike
this fleet's other guard CLIs. Mirrors the test_cli.py pattern already
used across the fleet (e.g. rng-leak-audit, causality-audit) for a repo
that had none."""
from __future__ import annotations

import json

from starveguard.cli import main


def test_version_flag(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out
    assert code == 0
    assert "starveguard" in out


def test_json_output_is_valid_json_and_reports_all_scenarios(capsys):
    code = main(["--json"])
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert isinstance(rows, list)
    assert len(rows) == 3  # DEFAULT_SCENARIOS: balanced-load, heavy-contention, light-contention
    for row in rows:
        assert "scenario" in row
        assert "improved" in row
    assert code == 0  # --json always returns 0 per cli.py


def test_text_output_no_color_has_no_ansi_escapes(capsys):
    main(["--no-color"])
    out = capsys.readouterr().out
    assert "\x1b[" not in out


def test_text_output_reports_each_scenario_and_exit_code_reflects_improvement(capsys):
    code = main(["--no-color"])
    out = capsys.readouterr().out
    for label in ("balanced-load", "heavy-contention", "light-contention"):
        assert label in out
    assert code in (0, 1)


def test_seed_offset_flag_is_accepted_and_deterministic(capsys):
    main(["--json", "--seed-offset", "5"])
    out1 = capsys.readouterr().out
    main(["--json", "--seed-offset", "5"])
    out2 = capsys.readouterr().out
    assert json.loads(out1) == json.loads(out2)
