import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

import transcriber.web as web
from transcriber.core import transcribe_audio_windows


class StandaloneASRTests(unittest.TestCase):
    def test_fixed_windows_stay_below_short_model_limit(self):
        class RawWord:
            start = 0.5
            end = 1.0
            text = "Фраза."

        class Result:
            words = [RawWord()]
            text = "Фраза."

        class Model:
            def __init__(self):
                self.durations = []

            def transcribe(self, path, word_timestamps=False):
                with wave.open(path, "rb") as audio:
                    self.durations.append(
                        audio.getnframes() / audio.getframerate()
                    )
                self.word_timestamps = word_timestamps
                return Result()

        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "meeting.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(
                    (array("h", [1_000]) * (41 * 16_000)).tobytes()
                )
            model = Model()

            segments = transcribe_audio_windows(
                audio_path,
                "cpu",
                model_loader=lambda _device: model,
            )

        self.assertEqual(len(model.durations), 3)
        self.assertTrue(all(duration <= 21.5 for duration in model.durations))
        self.assertTrue(model.word_timestamps)
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(left.end <= right.start for left, right in zip(segments, segments[1:])))

    def test_file_mode_without_diarization_does_not_require_pyannote(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            txt = output / "meeting.txt"
            json_path = output / "meeting.json"
            docx = output / "meeting.docx"
            for path in (txt, json_path, docx):
                path.write_bytes(b"result")

            with (
                patch.object(web, "prepare_pyannote_models") as prepare,
                patch.object(
                    web,
                    "run",
                    return_value=(txt, json_path, docx, "cpu", False),
                ) as run,
            ):
                web._process(
                    "job",
                    [Path("meeting.m4a")],
                    "cpu",
                    None,
                    False,
                    None,
                    True,
                    "auto",
                    "v3_e2e_rnnt",
                )

        prepare.assert_not_called()
        self.assertTrue(run.call_args.kwargs["local_windowing"])


if __name__ == "__main__":
    unittest.main()
