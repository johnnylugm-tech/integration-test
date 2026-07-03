#!/bin/bash
cd /Users/johnny/projects/integration-test
./.venv/bin/ruff check 03-development/src/ --extend-ignore RUF001,RUF002,RUF003 > .ruff_output.txt 2>&1
echo "EXIT:$?" >> .ruff_output.txt