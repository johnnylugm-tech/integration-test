#!/bin/bash
exec python -m pytest 03-development/tests/test_fr02.py --cov=03-development/src --cov-report=term-missing -q