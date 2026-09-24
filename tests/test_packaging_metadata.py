"""Regression tests for current pyproject license metadata."""
from __future__ import annotations

from pathlib import Path


def _pyproject_text() -> str:
    return (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()


def test_pyproject_uses_spdx_license_expression():
    text = _pyproject_text()
    assert 'license = "MIT"' in text
    assert 'license = { text = "MIT" }' not in text
    assert "License :: OSI Approved :: MIT License" not in text


def test_pyproject_declares_license_files_for_build_backend():
    text = _pyproject_text()
    assert 'license-files = ["LICENSE"]' in text
    assert 'requires = ["setuptools>=77"]' in text
