"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_grandplan_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Point GRANDPLAN_HOME at a unique temp dir for every test (hermetic by default).

    The persistent index/inbox live under GRANDPLAN_HOME (default ~/.grandplan). Now that `organize`
    persists there too, an unset home would leak real-filesystem state across tests. A test that needs
    a specific home still overrides this with its own `monkeypatch.setenv` in the body.
    """
    monkeypatch.setenv("GRANDPLAN_HOME", str(tmp_path_factory.mktemp("grandplan-home")))
