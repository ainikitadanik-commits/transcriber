import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from transcriber.realtime import (
    PCMBuffer,
    RealtimeCaptureManager,
    capture_helper_path,
)


class RealtimeTests(unittest.TestCase):
    def test_native_capture_sources_are_independent_and_structured(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "native"
            / "realtime_capture.swift"
        ).read_text(encoding="utf-8")

        self.assertIn("import CoreAudio", source)
        self.assertIn("AudioHardwareCreateProcessTap", source)
        self.assertIn("AudioHardwareDestroyProcessTap", source)
        self.assertIn("final class MicrophoneCapture", source)
        self.assertIn("AVAudioEngine()", source)
        self.assertIn("guard let systemFD else", source)
        self.assertIn("let microphoneCapture = microphoneFD.map", source)
        self.assertNotIn("ScreenCaptureKit", source)
        self.assertIn("GET /api/health HTTP/1.0", source)
        self.assertIn('environment["TRANSCRIBER_BUILD_ID"]', source)
        self.assertIn('environment["TRANSCRIBER_INSTANCE_ID"]', source)
        self.assertIn('appendingPathComponent("runtime-instance.json")', source)
        self.assertIn('expectedPID.map { payload?["pid"]', source)
        self.assertIn("removeRuntimeMarker(ifMatching:", source)
        self.assertNotIn('text.contains("\\"audio_format\\"")', source)
        for field in (
            '"source"',
            '"error_domain"',
            '"error_code"',
            '"native_code"',
            '"state"',
        ):
            self.assertIn(field, source)

    def test_pcm_buffer_is_bounded_and_drains_in_order(self):
        buffer = PCMBuffer(limit=6)
        buffer.append(b"abcd")
        buffer.append(b"efgh")

        self.assertEqual(buffer.total_bytes, 8)
        self.assertEqual(buffer.buffered_bytes, 6)
        self.assertEqual(buffer.drain(4), b"cdef")
        self.assertEqual(buffer.drain(), b"gh")

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
        self.assertEqual(
            state["audio_format"],
            {
                "sample_rate": 16000,
                "channels": 1,
                "sample_width": 2,
                "encoding": "pcm_s16le",
            },
        )

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

    def test_system_only_start_does_not_open_microphone_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "realtime-capture"
            helper.touch()
            helper.chmod(0o755)
            process = Mock()
            process.stdout = []
            with (
                patch.dict(os.environ, {"TRANSCRIBER_CAPTURE_HELPER": str(helper)}),
                patch("transcriber.realtime.os.pipe", return_value=(10, 11)) as pipe,
                patch("transcriber.realtime.os.close"),
                patch("transcriber.realtime.subprocess.Popen", return_value=process) as popen,
                patch("transcriber.realtime.threading.Thread") as thread,
            ):
                state = RealtimeCaptureManager().start()

        pipe.assert_called_once_with()
        command = popen.call_args.args[0]
        self.assertEqual(command, [str(helper), "--system-fd", "11"])
        self.assertEqual(popen.call_args.kwargs["pass_fds"], (11,))
        self.assertEqual(thread.call_count, 3)
        self.assertFalse(state["microphone_enabled"])
        self.assertEqual(state["permissions"]["microphone"], "disabled")


if __name__ == "__main__":
    unittest.main()
