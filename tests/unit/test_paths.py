"""Tests for core/paths.py."""

import pathlib

import pytest

# We test via the public API – import after env-var is set by the fixture.


def test_data_dir_uses_env_var(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """STUDY_TRACKER_HOME overrides the default location."""
    monkeypatch.setenv("STUDY_TRACKER_HOME", str(tmp_path / "custom"))
    # Re-import to pick up the new env var.
    import importlib

    import study_tracker.core.paths as p

    importlib.reload(p)
    assert p.data_dir() == (tmp_path / "custom").resolve()


def test_data_dir_is_created(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """data_dir() creates the directory if it does not exist."""
    target = tmp_path / "new_dir"
    monkeypatch.setenv("STUDY_TRACKER_HOME", str(target))
    import importlib

    import study_tracker.core.paths as p

    importlib.reload(p)
    result = p.data_dir()
    assert result.is_dir()


def test_paths_are_under_data_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """db_path, log_path, backup_dir, and lock_path are all under data_dir."""
    monkeypatch.setenv("STUDY_TRACKER_HOME", str(tmp_path))
    import importlib

    import study_tracker.core.paths as p

    importlib.reload(p)
    base = p.data_dir()
    assert str(p.db_path()).startswith(str(base))
    assert str(p.log_path()).startswith(str(base))
    assert str(p.backup_dir()).startswith(str(base))
    assert str(p.lock_path()).startswith(str(base))


def test_no_relative_paths(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All returned paths are absolute regardless of the working directory."""
    monkeypatch.setenv("STUDY_TRACKER_HOME", str(tmp_path))
    import importlib

    import study_tracker.core.paths as p

    importlib.reload(p)
    for fn in (p.data_dir, p.db_path, p.log_path, p.backup_dir, p.lock_path):
        assert fn().is_absolute(), f"{fn.__name__}() returned a relative path"
