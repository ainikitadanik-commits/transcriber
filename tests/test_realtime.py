import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcriber.realtime import RealtimeCaptureManager, capture_helper_path


class RealtimeTests(unittest.TestCase):
    def test_configured_capture_helper_path_is_used(self):
        with patch.dict(
            os.environ,
            {"TRANSCRIBER_CAPTURE_HELPER": "~/custom/realtime-capture"},
        ):
            path = capture_helper_path()

        self.assertEqual(path, Path.home() / "custom" / "realtime-capture")

    def test_snapshot_reports_executable_helper_as_available(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "realtime-capture"
            helper.touch()
            helper.chmod(0o755)
            with patch.dict(
                os.environ,
                {"TRANSCRIBER_CAPTURE_HELPER": str(helper)},
            ):
                state = RealtimeCaptureManager().snapshot()

        self.assertTrue(state["available"])
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["elapsed_seconds"], 0)

    def test_permission_error_has_actionable_message(self):
        message = RealtimeCaptureManager._friendly_error(
            "Screen capture permission denied"
        )

        self.assertIn("Системных настройках", message)
        self.assertIn("микрофон", message)

    def test_start_without_helper_has_build_instruction(self):
        manager = RealtimeCaptureManager()
        with patch.dict(
            os.environ,
            {"TRANSCRIBER_CAPTURE_HELPER": "/missing/realtime-capture"},
        ):
            with self.assertRaisesRegex(RuntimeError, "build_realtime_helper"):
                manager.start()


if __name__ == "__main__":
    unittest.main()
