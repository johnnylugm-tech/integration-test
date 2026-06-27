#!/bin/bash
set -e
exec /Users/johnny/.local/bin/python3 -m pytest 03-development/tests/test_fr01.py --cov=03-development/src --cov-report=term-missing -q