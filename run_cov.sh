#!/bin/bash
cd /Users/johnny/projects/integration-test
exec .venv/bin/pytest 03-development/tests/test_fr03.py --cov=03-development/src --cov-report=term-missing -q "$@"