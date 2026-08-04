import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeEntryTests(unittest.TestCase):
    def test_pyannote_metrics_are_disabled_before_application_import(self):
        probe = """
import os
import runpy
import sys
import types

os.environ.pop("PYANNOTE_METRICS_ENABLED", None)
web = types.ModuleType("transcriber.web")

def module_getattr(name):
    if name == "main":
        print(os.environ.get("PYANNOTE_METRICS_ENABLED"))
        return lambda: 0
    raise AttributeError(name)

web.__getattr__ = module_getattr
sys.modules["transcriber.web"] = web
runpy.run_path("packaging/runtime_entry.py", run_name="runtime_entry_probe")
"""
        environment = os.environ.copy()
        environment.pop("PYANNOTE_METRICS_ENABLED", None)
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
