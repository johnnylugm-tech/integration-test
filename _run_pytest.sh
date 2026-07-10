#!/bin/bash
export PYTHONPATH=03-development/src
.venv/bin/pytest 03-development/tests -q --tb=short
