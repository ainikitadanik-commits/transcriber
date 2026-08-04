import unittest
from types import SimpleNamespace

import numpy as np

from transcriber.realtime_diarization import PyannoteRealtimeDiarizer


class FakeTurn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class FakeAnnotation:
    def __init__(self, tracks):
        self.tracks = tracks

    def labels(self):
        return list(dict.fromkeys(label for _start, _end, label in self.tracks))

    def itertracks(self, yield_label=False):
        del yield_label
        for start, end, label in self.tracks:
            yield FakeTurn(start, end), None, label


class FakePipeline:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def __call__(self, audio):
        self.audio = audio
        return next(self.outputs)


def output(tracks, embeddings):
    return SimpleNamespace(
        exclusive_speaker_diarization=FakeAnnotation(tracks),
        speaker_embeddings=np.asarray(embeddings, dtype=np.float32),
    )


class RealtimeDiarizationTests(unittest.TestCase):
    def test_embeddings_keep_anonymous_speaker_names_across_windows(self):
        pipeline = FakePipeline(
            [
                output(
                    [(0.0, 1.0, "A"), (1.0, 2.0, "B")],
                    [[1.0, 0.0], [0.0, 1.0]],
                ),
                output(
                    [(0.0, 1.0, "X"), (1.0, 2.0, "Y")],
                    [[0.02, 0.99], [0.99, 0.02]],
                ),
            ]
        )
        diarizer = PyannoteRealtimeDiarizer(pipeline)
        pcm = b"\0\0" * 32_000

        first = diarizer("system", pcm, 16_000)
        second = diarizer("system", pcm, 16_000)

        self.assertEqual([turn.speaker for turn in first], ["Спикер 1", "Спикер 2"])
        self.assertEqual([turn.speaker for turn in second], ["Спикер 2", "Спикер 1"])

    def test_microphone_is_not_diarized(self):
        pipeline = FakePipeline([])
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        self.assertEqual(diarizer("microphone", b"\0\0", 16_000), ())


if __name__ == "__main__":
    unittest.main()
