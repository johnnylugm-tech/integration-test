#!/bin/bash
cd /Users/johnny/projects/integration-test
/Users/johnny/projects/integration-test/.venv/bin/pytest tests/test_fr03.py --cov=03-development/src --cov-report=term-missing -q > /Users/johnny/projects/integration-test/.covout.txt 2>&1
echo "EXIT $?"