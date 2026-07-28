import tempfile
import time
import unittest
from pathlib import Path

from transcriber.realtime_service import RealtimeTranscriptionService


class FakeCapture:
    def __init__(self, system: bytes = b"", microphone: bytes = b"") -> None:
        self.audio = {
            "system": bytearray(system),
            "microphone": bytearray(microphone),
        }
        self.status = "idle"
        self.stop_calls = 0

    def start(self):
        self.status = "recording"
        return self.snapshot()

    def stop(self):
        self.stop_calls += 1
        self.status = "idle"
        return self.snapshot()

    def snapshot(self):
        return {
            "status": self.status,
            "message": "capture",
            "available": True,
            "elapsed_seconds": 1,
            "system_audio": bool(self.audio["system"]),
            "microphone": bool(self.audio["microphone"]),
        }

    def drain_audio(self, source, max_bytes=None):
        buffer = self.audio[source]
        count = len(buffer) if max_bytes is None else min(max_bytes, len(buffer))
        result = bytes(buffer[:count])
        del buffer[:count]
        return result


class RealtimeServiceTests(unittest.TestCase):
    def test_stop_when_idle_is_non_blocking(self):
        capture = FakeCapture()
        service = RealtimeTranscriptionService(capture, Path("/unused"))

        started = time.monotonic()
        state = service.stop()

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(state["status"], "idle")

    def test_capture_to_local_exports_without_pcm_files(self):
        one_second = b"\x01\x00" * 16_000
        capture = FakeCapture(one_second, one_second)
        calls = []

        def adapter(source, pcm, sample_rate):
            calls.append((source, len(pcm), sample_rate))
            return "тестовая реплика"

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            service = RealtimeTranscriptionService(
                capture,
                output_dir,
                adapter_loader=lambda: (adapter, "cpu"),
                window_seconds=0.5,
                overlap_seconds=0.1,
                poll_interval=0.01,
            )

            started = service.start()
            self.assertEqual(started["status"], "recording")
            deadline = time.monotonic() + 2
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            stopping = service.stop()
            self.assertIn(stopping["asr_status"], {"finalizing", "done"})
            self.assertTrue(service.wait(2))
            final = service.snapshot()

            self.assertEqual(final["asr_status"], "done")
            self.assertGreaterEqual(len(final["segments"]), 2)
            self.assertTrue((output_dir / final["txt_name"]).is_file())
            self.assertTrue((output_dir / final["json_name"]).is_file())
            self.assertTrue((output_dir / final["docx_name"]).is_file())
            self.assertFalse(list(output_dir.glob("*.pcm")))
            self.assertEqual({call[0] for call in calls}, {"system", "microphone"})
            self.assertTrue(all(call[2] == 16_000 for call in calls))

    def test_model_failure_stops_capture_and_reports_error(self):
        capture = FakeCapture()
        service = RealtimeTranscriptionService(
            capture,
            Path("/unused"),
            adapter_loader=lambda: (_ for _ in ()).throw(RuntimeError("model")),
            poll_interval=0.01,
        )

        service.start()
        self.assertTrue(service.wait(2))
        state = service.snapshot()

        self.assertEqual(state["asr_status"], "error")
        self.assertGreaterEqual(capture.stop_calls, 1)


if __name__ == "__main__":
    unittest.main()
