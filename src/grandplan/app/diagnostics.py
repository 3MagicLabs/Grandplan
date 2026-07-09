"""Diagnosability (#5): persistent rotating log + sys/threading excepthooks.

Before this, logs went only to the console — a crash with the console closed (or a hotkey-listener
thread dying quietly, hit during stress testing) left NO trace anywhere. `install_diagnostics`
gives every run a durable record:

- a **rotating file log** under the vault's index root (`<index>/logs/grandplan.log`, 1 MiB × 3
  backups — bounded, offline, next to the data it describes);
- **`sys.excepthook` + `threading.excepthook`** so an unhandled exception on ANY thread is written
  with its full traceback and thread name before the process dies. Both hooks CHAIN to the
  originals (a debugger's or pytest's hook still runs — never silently replaced).

Idempotent: re-installing (e.g. tests, a second `run_app` in one process) never stacks duplicate
handlers. `--debug` raises both file and console verbosity to DEBUG.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

_MAX_BYTES = 1_000_000  # ~1 MiB per file, 3 backups: bounded even for a chatty long-running tray
_BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
_MARKER = "_grandplan_diagnostics"  # tags our file handler so install is idempotent
_CONSOLE_MARKER = "_grandplan_console"  # tags our --debug console handler (idempotent)


def install_diagnostics(index_root: Path, *, debug: bool = False) -> Path:
    """Attach the rotating file handler (+ a console handler under --debug) + crash hooks.

    Returns the log file path. `--debug` streams DEBUG to the console: we add a StreamHandler
    OURSELVES rather than calling `logging.basicConfig`, which is a silent no-op once the file
    handler below has populated `root.handlers` (the bug that made `--debug` print nothing).
    """
    log_dir = index_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "grandplan.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    if not any(getattr(h, _MARKER, False) for h in root.handlers):
        handler = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _MARKER, True)
        root.addHandler(handler)

    if debug and not any(getattr(h, _CONSOLE_MARKER, False) for h in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter(_FORMAT))
        setattr(console, _CONSOLE_MARKER, True)
        root.addHandler(console)

    _install_excepthooks()
    logger.info("diagnostics: logging to %s (debug=%s)", log_path, debug)
    return log_path


def _install_excepthooks() -> None:
    """Chain crash logging in front of the current sys/threading hooks (idempotently)."""
    if not getattr(sys.excepthook, _MARKER, False):
        original_sys = sys.excepthook

        def _sys_hook(
            exc_type: type[BaseException],
            value: BaseException,
            traceback: TracebackType | None,
        ) -> None:
            logger.critical(
                "unhandled exception (main thread)", exc_info=(exc_type, value, traceback)
            )
            original_sys(exc_type, value, traceback)

        setattr(_sys_hook, _MARKER, True)
        sys.excepthook = _sys_hook

    if not getattr(threading.excepthook, _MARKER, False):
        original_threading = threading.excepthook

        def _thread_hook(args: threading.ExceptHookArgs) -> None:
            name = args.thread.name if args.thread is not None else "<unknown>"
            logger.critical(
                "unhandled exception in thread %r",
                name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # type: ignore[arg-type]
            )
            original_threading(args)

        setattr(_thread_hook, _MARKER, True)
        threading.excepthook = _thread_hook
