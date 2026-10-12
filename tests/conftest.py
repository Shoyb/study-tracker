"""Shared pytest fixtures and configuration."""

import pathlib

import pytest


@pytest.fixture()
def data_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Redirect all data-dir access to a temporary directory."""
    monkeypatch.setenv("STUDY_TRACKER_HOME", str(tmp_path))
    return tmp_path
