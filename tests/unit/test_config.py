"""Tests for Config.from_env()."""

from __future__ import annotations

import pytest

from src.config import Config


def test_loads_from_env() -> None:
    cfg = Config.from_env()
    assert cfg.project_id == "YOUR_GCP_PROJECT_ID"
    assert cfg.environment == "sandbox"
    assert cfg.is_sandbox is True


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
        Config.from_env()


def test_secret_suffix_matches_environment() -> None:
    cfg = Config.from_env()
    assert cfg.secret_suffix == "sandbox"
