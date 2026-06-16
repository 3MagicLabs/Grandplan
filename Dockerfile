# Reproducible environment for the grandplan CORE (headless, gated).
#
# Scope: builds/tests the platform-agnostic core and runs the same checks as the borromeo gate
# (format, lint, typecheck, test+coverage, security). The Windows adapters (global-hotkey capture,
# GUI, local LLM runtime) are NOT containerized — they require Windows and are tested there.

FROM python:3.12-slim

# Quality-gate tooling (mirrors borromeo's Python checks)
RUN pip install --no-cache-dir \
    ruff==0.15.8 \
    mypy==1.19.1 \
    pytest==8.3.3 \
    pytest-cov==7.0.0 \
    bandit==1.9.4

WORKDIR /app
COPY . .

# Run the mirrored gate by default. Greenfield-tolerant: skips build/typecheck/test/security
# when there is no Python source yet (consistent with borromeo's greenfield behavior).
CMD bash -c '\
  set -e; \
  echo "== format =="; ruff format --check .; \
  echo "== lint ==";   ruff check .; \
  if [ -n "$(find src -name "*.py" -print -quit 2>/dev/null)" ]; then \
    echo "== build ==";     python -m compileall -q src; \
    echo "== typecheck =="; mypy src; \
    echo "== security =="; bandit -q -r src; \
    echo "== test ==";     pytest -q --cov; \
  else \
    echo "greenfield: no python source yet — build/typecheck/test/security skipped"; \
  fi'
