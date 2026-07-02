#!/bin/bash
cd /Users/johnny/projects/integration-test
/Users/johnny/projects/integration-test/.venv/bin/pytest 03-development/tests/test_fr03.py --cov=03-development/src --cov-report=term-missing -q --no-header -p no:cacheprovider > /Users/johnny/projects/integration-test/_fr03_cov_out.txt 2>&1
echo "EXIT=$?"
