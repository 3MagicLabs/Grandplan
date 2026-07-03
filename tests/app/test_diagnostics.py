"""Diagnosability (#5): rotating file log + sys/threading excepthooks.

The failure this exists for: a crash (or a hotkey thread dying) with the console closed left NO
trace anywhere — observed during stress testing. After `install_diagnostics`, an unhandled
exception on ANY thread lands in a rotating log file with a full traceback, and the hooks chain
to the originals (never replace debugger/pytest hooks silently).
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import pytest

from grandplan.app.diagnostics import install_diagnostics


@pytest.fixture(autouse=True)
def _restore_hooks_and_handlers():  # type: ignore[no-untyped-def]
    """Tests install global hooks/handlers — always restore, or later tests inherit them."""
    sys_hook, thread_hook = sys.excepthook, threading.excepthook
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    sys.excepthook, threading.excepthook = sys_hook, thread_hook
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_install_creates_log_file_and_captures_log_records(tmp_path: Path) -> None:
    log_path = install_diagnostics(tmp_path)
    assert log_path == tmp_path / "logs" / "grandplan.log"
    logging.getLogger("grandplan.test").warning("hello from the test")
    assert "hello from the test" in log_path.read_text(encoding="utf-8")


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_worker_thread_crash_is_written_with_traceback(tmp_path: Path) -> None:
    # The deliberate thread crash chains through to pytest's own watcher (proof the chain works) —
    # its warning about the exception WE raised is expected, not a defect.
    log_path = install_diagnostics(tmp_path)

    def boom() -> None:
        raise RuntimeError("hotkey thread died")

    thread = threading.Thread(target=boom, name="grandplan-hotkey")
    thread.start()
    thread.join()
    text = log_path.read_text(encoding="utf-8")
    assert "hotkey thread died" in text
    assert "Traceback" in text  # full traceback, not just the message
    assert "grandplan-hotkey" in text  # WHICH thread died is the diagnostic gold


def test_sys_excepthook_logs_and_chains_to_original(tmp_path: Path) -> None:
    seen: list[str] = []
    sys.excepthook = lambda tp, value, tb: seen.append(str(value))  # stand-in "original"
    log_path = install_diagnostics(tmp_path)
    try:
        raise ValueError("main thread crash")
    except ValueError:
        sys.excepthook(*sys.exc_info())  # what the interpreter would do
    assert "main thread crash" in log_path.read_text(encoding="utf-8")
    assert seen == ["main thread crash"]  # the original hook still ran (chained, not replaced)


def test_install_is_idempotent_no_duplicate_handlers(tmp_path: Path) -> None:
    install_diagnostics(tmp_path)
    log_path = install_diagnostics(tmp_path)  # second install must not double-log
    logging.getLogger("grandplan.test").warning("once only")
    assert log_path.read_text(encoding="utf-8").count("once only") == 1


def test_debug_raises_verbosity(tmp_path: Path) -> None:
    log_path = install_diagnostics(tmp_path, debug=True)
    logging.getLogger("grandplan.test").debug("debug detail")
    assert "debug detail" in log_path.read_text(encoding="utf-8")
