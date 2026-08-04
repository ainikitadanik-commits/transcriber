import json
import tempfile
import time
import unittest
from pathlib import Path

from transcriber.realtime_service import RealtimeTranscriptionService
from transcriber.realtime_asr import (
    RealtimeASRResult,
    RealtimeSpeakerTurn,
    RealtimeWord,
)


class FakeCapture:
    def __init__(self, system: bytes = b"", microphone: bytes = b"") -> None:
        self.audio = {
            "system": bytearray(system),
            "microphone": bytearray(microphone),
        }
        self.status = "idle"
        self.stop_calls = 0
        self.include_microphone = None

    def start(self, *, include_microphone=False):
        self.include_microphone = include_microphone
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

            started = service.start(include_microphone=True)
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
            self.assertTrue(capture.include_microphone)

    def test_default_session_never_drains_or_transcribes_microphone(self):
        one_second = b"\x01\x00" * 16_000
        capture = FakeCapture(one_second, one_second)
        calls = []

        def adapter(source, pcm, sample_rate):
            calls.append(source)
            return "реплика"

        with tempfile.TemporaryDirectory() as directory:
            service = RealtimeTranscriptionService(
                capture,
                Path(directory),
                adapter_loader=lambda: (adapter, "cpu"),
                window_seconds=0.5,
                overlap_seconds=0.1,
                poll_interval=0.01,
            )
            service.start()
            deadline = time.monotonic() + 2
            while not calls and time.monotonic() < deadline:
                time.sleep(0.01)
            service.stop()
            self.assertTrue(service.wait(2))

        self.assertEqual(set(calls), {"system"})
        self.assertFalse(capture.include_microphone)
        self.assertEqual(len(capture.audio["microphone"]), len(one_second))

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

    def test_realtime_diarization_labels_live_segments_and_export(self):
        capture = FakeCapture(b"\x01\x00" * 16_000)
        loader_calls = []

        def adapter(_source, _pcm, _sample_rate):
            return RealtimeASRResult(
                "первая вторая",
                (
                    RealtimeWord(0.05, 0.2, "первая"),
                    RealtimeWord(0.25, 0.45, "вторая"),
                ),
            )

        def load_diarizer(device, token):
            loader_calls.append((device, token))
            return lambda _source, _pcm, _sample_rate: (
                RealtimeSpeakerTurn(0.0, 0.22, "Спикер 1"),
                RealtimeSpeakerTurn(0.22, 0.5, "Спикер 2"),
            )

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            service = RealtimeTranscriptionService(
                capture,
                output_dir,
                adapter_loader=lambda: (adapter, "cpu"),
                diarizer_loader=load_diarizer,
                window_seconds=0.5,
                overlap_seconds=0.1,
                poll_interval=0.01,
            )
            service.start(diarization=True, hf_token="hf_test")
            deadline = time.monotonic() + 2
            while not service.snapshot()["segments"] and time.monotonic() < deadline:
                time.sleep(0.01)
            service.stop()
            self.assertTrue(service.wait(2))
            final = service.snapshot()
            document = json.loads((output_dir / final["json_name"]).read_text())

        self.assertEqual(loader_calls, [("cpu", "hf_test")])
        self.assertEqual(
            {segment["speaker"] for segment in final["segments"]},
            {"Спикер 1", "Спикер 2"},
        )
        self.assertTrue(document["processing"]["diarization"]["enabled"])
        self.assertEqual(
            {segment["speaker"] for segment in document["segments"]},
            {"Спикер 1", "Спикер 2"},
        )


if __name__ == "__main__":
    unittest.main()
