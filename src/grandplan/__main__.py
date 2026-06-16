"""Enable `python -m grandplan` to run the CLI."""

from __future__ import annotations

from grandplan.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
