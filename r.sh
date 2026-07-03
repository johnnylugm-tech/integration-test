#!/bin/sh
exec /Users/johnny/projects/integration-test/.venv/bin/ruff check /Users/johnny/projects/integration-test/03-development/src/ --extend-ignore RUF001,RUF002,RUF003 "$@"