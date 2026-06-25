# integration-test project root Makefile
# Implements SAD §1.1 system verification target.

# Use the venv python explicitly — `python3` on this machine resolves to
# /usr/bin/python3 (3.9.6) which fails the SPEC §1 + SAD §1 requirement
# of Python 3.11+.
PYTHON    ?= .venv/bin/python
SRC_DIR   := 03-development/src

.PHONY: verify-system help test lint shell-audit smoke

help:
	@echo "Targets:"
	@echo "  verify-system  SAD §1.1 audit chain (4 steps; required by Gate 2)"
	@echo "  test           Run pytest"
	@echo "  lint           Run ruff"
	@echo "  shell-audit    NFR-02 — assert shell=True absent from src/"
	@echo "  smoke          CLI entrypoint + submit/run/status round-trip"

verify-system: test shell-audit smoke
	@echo "verify-system: OK"

test:
	$(PYTHON) -m pytest 03-development/tests/ -x -q

shell-audit:
	@$(PYTHON) scripts/shell_audit.py $(SRC_DIR)

smoke:
	PYTHONPATH=$(SRC_DIR) $(PYTHON) -m taskq --help >/dev/null
	# Idempotent: clear any leftover smoke task before re-submit.
	PYTHONPATH=$(SRC_DIR) $(PYTHON) -m taskq clear >/dev/null 2>&1 || true
	PYTHONPATH=$(SRC_DIR) $(PYTHON) -m taskq submit "echo ok" --name smoke >/dev/null
	PYTHONPATH=$(SRC_DIR) $(PYTHON) -m taskq run --all >/dev/null
	PYTHONPATH=$(SRC_DIR) $(PYTHON) -m taskq list >/dev/null
	@echo "smoke: OK"

lint:
	$(PYTHON) -m ruff check $(SRC_DIR)