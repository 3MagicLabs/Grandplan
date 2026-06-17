"""QAS-1 (offline, hard): the core pipeline must make ZERO non-loopback network egress.

The SPEC requires "an automated egress check asserts no non-loopback sockets." We enforce it by
forbidding `socket.connect`/`connect_ex` to any non-loopback address for the duration of a full
offline run (organize → embed → reconcile → write → project). The deterministic baseline does no
network I/O, so this passes — and it is a regression guard: if anyone later wires a network call
into the offline core, this test fails loudly. (The optional LLM/embedding adapters only ever talk
to localhost Ollama; that is integration-tested on the user's machine.)
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from grandplan.cli import organize_text
from grandplan.core.models import Source

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _host_of(address: object) -> str:
    return str(address[0]) if isinstance(address, tuple) else str(address)


@pytest.fixture
def forbid_non_loopback_egress(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto

    def _check(address: object) -> None:
        if _host_of(address) not in _LOOPBACK_HOSTS:
            raise AssertionError(f"network egress attempted to {address!r} (QAS-1 violation)")

    def guard_connect(self: socket.socket, address: object) -> object:
        _check(address)
        return real_connect(self, address)  # type: ignore[arg-type]

    def guard_connect_ex(self: socket.socket, address: object) -> object:
        _check(address)
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    def guard_sendto(self: socket.socket, data: object, *args: object) -> object:
        _check(args[-1])  # sendto(data, address) or sendto(data, flags, address): addr is last
        return real_sendto(self, data, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", guard_sendto)
    yield


def test_offline_core_pipeline_makes_no_non_loopback_egress(
    forbid_non_loopback_egress: None, tmp_path: Path
) -> None:
    summary = organize_text(
        "Buy milk and call the dentist.\n\nIdea: build a fully offline second brain.",
        source=Source(app="test"),
        created="2026-06-17T00:00:00+00:00",
        vault_dir=tmp_path / "vault",
    )
    assert summary.notes >= 1  # the full offline loop completed with egress forbidden
    assert (tmp_path / "vault" / "Plan.md").exists()


def test_egress_guard_actually_blocks_non_loopback(forbid_non_loopback_egress: None) -> None:
    # Negative control: prove the guard would catch a real egress attempt (so the test above
    # is meaningful, not vacuously green).
    with pytest.raises(AssertionError, match="QAS-1 violation"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("93.184.216.34", 80))
