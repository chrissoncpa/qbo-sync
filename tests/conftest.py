"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide minimum env vars needed for Config.from_env() in tests."""
    monkeypatch.setenv("GCP_PROJECT_ID", "YOUR_GCP_PROJECT_ID")
    monkeypatch.setenv("ENVIRONMENT", "sandbox")
    yield
