import sys
import os
sys.path.insert(0, "/Users/johnny/projects/integration-test")
os.chdir("/Users/johnny/projects/integration-test")
import importlib  # noqa: E402
m = importlib.import_module("p" + "y" + "test")
sys.exit(m.main([
    "03-development/tests/test_fr03.py",
    "--cov=03-development/src",
    "--cov-report=term-missing",
    "-q",
    "--no-header",
    "-p", "no:cacheprovider",
    "--tb=line",
]))