"""Adapters implementing core ports with real (optional-dependency) backends.

Each adapter conforms to a core port and isolates an optional dependency behind an injected
seam, so its logic is unit-testable here while the real backend (Ollama, sentence-transformers,
Windows capture) is integration-tested on the target machine.
"""

from __future__ import annotations
