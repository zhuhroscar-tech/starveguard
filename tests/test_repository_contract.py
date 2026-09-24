"""Repository-level contract tests for documentation, packaging, and CI.

These checks keep source-quality releases honest: release notes stay linked,
version metadata stays aligned, and the source distribution keeps enough
project context for downstream users to audit the package without cloning Git.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_VERSION = "0.1.2"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_required_project_files_exist():
    for relative in (
        "README.md",
        "README.zh-CN.md",
        "LICENSE",
        "CHANGELOG.md",
        "MANIFEST.in",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
    ):
        assert (ROOT / relative).is_file(), f"missing {relative}"


def test_readmes_link_release_history_and_license():
    for relative in ("README.md", "README.zh-CN.md"):
        text = _read(relative)
        assert "CHANGELOG.md" in text
        assert "LICENSE" in text
        assert "github.com/zhuhroscar-tech/starveguard/releases" in text


def test_changelog_documents_current_release_and_history():
    changelog = _read("CHANGELOG.md")
    assert f"## v{CURRENT_VERSION}" in changelog
    assert "## v0.1.1" in changelog
    assert "## v0.1.0" in changelog
    assert "SPDX" in changelog
    assert "Initial public release" in changelog


def test_package_version_matches_changelog_current_entry():
    pyproject = _read("pyproject.toml")
    init = _read("src/starveguard/__init__.py")
    version_line = f'version = "{CURRENT_VERSION}"'
    assert version_line in pyproject
    assert f'__version__ = "{CURRENT_VERSION}"' in init
    assert f"## v{CURRENT_VERSION}" in _read("CHANGELOG.md")


def test_manifest_includes_release_and_ci_context():
    manifest = _read("MANIFEST.in")
    for expected in (
        "include CHANGELOG.md",
        "include README.md",
        "include README.zh-CN.md",
        "recursive-include tests *.py",
        "recursive-include .github/workflows *.yml",
    ):
        assert expected in manifest


def test_ci_builds_release_artifacts_and_codeql_is_enabled():
    ci = _read(".github/workflows/ci.yml")
    assert "python -m build" in ci
    assert "sha256sum * > SHA256SUMS.txt" in ci
    assert "actions/upload-artifact@v4" in ci
    assert "starveguard --json" in ci

    codeql = _read(".github/workflows/codeql.yml")
    assert "github/codeql-action/init@v3" in codeql
    assert "github/codeql-action/analyze@v3" in codeql
    assert re.search(r"languages:\s*python", codeql)
