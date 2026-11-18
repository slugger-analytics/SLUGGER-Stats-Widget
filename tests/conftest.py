"""Shared test setup.

The widget loads ``.env`` on start, so a developer who has a real Trackman key
in their ``.env`` would otherwise run every test against it. An empty
ALPB_API_KEY in the environment stops that, because python-dotenv never
overrides a variable that is already set. Tests that need Trackman set their
own fake key with ``monkeypatch.setenv``.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_trackman_key(monkeypatch):
    monkeypatch.setenv("ALPB_API_KEY", "")
