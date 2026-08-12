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


def output(tracks, embeddings, *, profile_tracks=None):
    return SimpleNamespace(
        speaker_diarization=FakeAnnotation(profile_tracks or tracks),
        exclusive_speaker_diarization=FakeAnnotation(tracks),
        speaker_embeddings=(
            None
            if embeddings is None
            else np.asarray(embeddings, dtype=np.float32)
        ),
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

        self.assertEqual(
            [turn.speaker for turn in first],
            ["Спикер не определён", "Спикер не определён"],
        )
        self.assertEqual([turn.speaker for turn in second], ["Спикер 2", "Спикер 1"])

    def test_microphone_is_not_diarized(self):
        pipeline = FakePipeline([])
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        self.assertEqual(diarizer("microphone", b"\0\0", 16_000), ())

    def test_embeddings_follow_full_diarization_labels(self):
        pipeline = FakePipeline(
            [
                output(
                    [(0.0, 1.0, "A")],
                    [[1.0, 0.0], [0.0, 1.0]],
                    profile_tracks=[
                        (0.0, 1.0, "A"),
                        (0.5, 1.0, "B"),
                    ],
                )
            ]
        )
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        turns = diarizer("system", b"\0\0" * 16_000, 16_000)

        self.assertEqual([turn.speaker for turn in turns], ["Спикер не определён"])

    def test_missing_embeddings_keep_turns_with_unknown_speaker(self):
        pipeline = FakePipeline([output([(0.0, 1.0, "A")], None)])
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        turns = diarizer("system", b"\0\0" * 16_000, 16_000)

        self.assertEqual(
            [turn.speaker for turn in turns],
            ["Спикер не определён"],
        )

    def test_dissimilar_one_off_embeddings_do_not_create_profiles(self):
        pipeline = FakePipeline(
            [
                output([(0.0, 1.0, "A")], [np.eye(8)[index]])
                for index in range(8)
            ]
        )
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        speakers = []
        for _ in range(8):
            turns = diarizer("system", b"\0\0" * 16_000, 16_000)
            speakers.extend(turn.speaker for turn in turns)

        self.assertEqual(set(speakers), {"Спикер не определён"})
        self.assertEqual(diarizer._profiles, [])

    def test_recurring_voice_is_confirmed_as_one_profile(self):
        pipeline = FakePipeline(
            [
                output([(0.0, 1.0, "A")], [[1.0, 0.0]]),
                output([(0.0, 1.0, "B")], [[0.99, 0.01]]),
                output([(0.0, 1.0, "C")], [[1.0, 0.02]]),
                output([(0.0, 1.0, "D")], [[1.0, 0.0, 0.0]]),
            ]
        )
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        first = diarizer("system", b"\0\0" * 16_000, 16_000)
        second = diarizer("system", b"\0\0" * 16_000, 16_000)
        third = diarizer("system", b"\0\0" * 16_000, 16_000)
        mismatched = diarizer("system", b"\0\0" * 16_000, 16_000)

        self.assertEqual(first[0].speaker, "Спикер не определён")
        self.assertEqual(second[0].speaker, "Спикер 1")
        self.assertEqual(third[0].speaker, "Спикер 1")
        self.assertEqual(mismatched[0].speaker, "Спикер не определён")
        self.assertEqual(len(diarizer._profiles), 1)

    def test_profile_cap_is_never_exceeded(self):
        outputs = []
        for index in range(3):
            embedding = [0.0, 0.0, 0.0]
            embedding[index] = 1.0
            outputs.extend(
                [
                    output([(0.0, 1.0, "A")], [embedding]),
                    output([(0.0, 1.0, "B")], [embedding]),
                ]
            )
        diarizer = PyannoteRealtimeDiarizer(
            FakePipeline(outputs), max_profiles=2
        )

        speakers = [
            diarizer("system", b"\0\0" * 16_000, 16_000)[0].speaker
            for _ in outputs
        ]

        self.assertEqual(len(diarizer._profiles), 2)
        self.assertEqual(speakers[-1], "Спикер не определён")

    def test_invalid_and_mismatched_embeddings_degrade_to_unknown(self):
        pipeline = FakePipeline(
            [
                output([(0.0, 1.0, "A")], [[float("nan"), 0.0]]),
                output([(0.0, 0.2, "A")], [[1.0, 0.0]]),
                output([(0.0, 1.0, "A")], 1.0),
                output(
                    [(0.0, 1.0, "A"), (1.0, 2.0, "B")],
                    [[1.0, 0.0]],
                ),
            ]
        )
        diarizer = PyannoteRealtimeDiarizer(pipeline)

        speakers = []
        for _ in range(4):
            speakers.extend(
                turn.speaker
                for turn in diarizer("system", b"\0\0" * 32_000, 16_000)
            )

        self.assertEqual(set(speakers), {"Спикер не определён"})
        self.assertEqual(diarizer._profiles, [])


if __name__ == "__main__":
    unittest.main()
