#!/bin/bash
cd /Users/johnny/projects/integration-test
exec /Users/johnny/Library/Python/3.9/bin/pytest 03-development/tests/test_fr01.py --cov=03-development/src --cov-report=term-missing -q