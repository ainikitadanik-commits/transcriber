import unittest

from transcriber.realtime_asr import (
    BackpressureError,
    RealtimeASRResult,
    RealtimeASRSession,
    RealtimeSpeakerTurn,
    RealtimeWord,
    SOURCE_MICROPHONE,
    SOURCE_SYSTEM,
    longest_token_overlap,
)


SAMPLE_RATE = 16_000


def silent_pcm(seconds: float) -> bytes:
    return b"\0\0" * round(seconds * SAMPLE_RATE)


class FakeASR:
    def __init__(self, responses):
        self.responses = {
            source: iter(source_responses)
            for source, source_responses in responses.items()
        }
        self.calls = []

    def __call__(self, source, pcm, sample_rate):
        self.calls.append((source, len(pcm), sample_rate))
        return next(self.responses[source])


class FakeCapture:
    def __init__(self, chunks):
        self.chunks = dict(chunks)
        self.calls = []

    def drain_audio(self, source, max_bytes=None):
        self.calls.append((source, max_bytes))
        return self.chunks.pop(source, b"")[:max_bytes]


class RealtimeASRTests(unittest.TestCase):
    def test_session_can_exclude_microphone_source(self):
        session = RealtimeASRSession(
            lambda source, pcm, sample_rate: "текст",
            sources=(SOURCE_SYSTEM,),
            window_seconds=1,
            overlap_seconds=0.2,
        )

        with self.assertRaisesRegex(ValueError, "Неизвестный источник"):
            session.push(SOURCE_MICROPHONE, b"\x00\x00")

    def test_rejects_windows_above_gigaam_short_audio_limit(self):
        with self.assertRaisesRegex(ValueError, "25"):
            RealtimeASRSession(lambda *_args: "", window_seconds=25.1)

    def test_schedules_overlapping_windows_and_commits_stable_tokens(self):
        asr = FakeASR(
            {
                SOURCE_SYSTEM: [
                    "один два три",
                    "три четыре пять",
                ],
            }
        )
        session = RealtimeASRSession(
            asr,
            window_seconds=1.0,
            overlap_seconds=0.25,
        )

        session.push(SOURCE_SYSTEM, silent_pcm(1.75))
        snapshot = session.process_ready(max_windows=2)

        self.assertEqual(
            asr.calls,
            [
                (SOURCE_SYSTEM, 2 * SAMPLE_RATE, SAMPLE_RATE),
                (SOURCE_SYSTEM, 2 * SAMPLE_RATE, SAMPLE_RATE),
            ],
        )
        self.assertEqual(
            [(segment.source, segment.text) for segment in snapshot.committed],
            [(SOURCE_SYSTEM, "один два")],
        )
        self.assertEqual(snapshot.provisional[SOURCE_SYSTEM].text, "три четыре пять")
        self.assertAlmostEqual(snapshot.provisional[SOURCE_SYSTEM].start, 0.75)
        self.assertAlmostEqual(snapshot.provisional[SOURCE_SYSTEM].end, 1.75)

    def test_scheduler_is_fair_across_system_and_microphone(self):
        asr = FakeASR(
            {
                SOURCE_SYSTEM: ["системный звук"],
                SOURCE_MICROPHONE: ["голос пользователя"],
            }
        )
        session = RealtimeASRSession(asr, window_seconds=1.0, overlap_seconds=0.2)
        session.push(SOURCE_SYSTEM, silent_pcm(1.0))
        session.push(SOURCE_MICROPHONE, silent_pcm(1.0))

        snapshot = session.process_ready(max_windows=2)

        self.assertEqual(
            [call[0] for call in asr.calls],
            [SOURCE_SYSTEM, SOURCE_MICROPHONE],
        )
        self.assertEqual(
            set(snapshot.provisional),
            {SOURCE_SYSTEM, SOURCE_MICROPHONE},
        )

    def test_capture_is_dependency_injected(self):
        asr = FakeASR(
            {
                SOURCE_SYSTEM: ["система"],
                SOURCE_MICROPHONE: ["микрофон"],
            }
        )
        capture = FakeCapture(
            {
                SOURCE_SYSTEM: silent_pcm(1.0),
                SOURCE_MICROPHONE: silent_pcm(1.0),
            }
        )
        session = RealtimeASRSession(
            asr,
            capture=capture,
            window_seconds=1.0,
            overlap_seconds=0.2,
        )

        snapshot = session.pull_capture(max_windows=2)

        self.assertEqual(len(capture.calls), 2)
        self.assertEqual(
            set(snapshot.provisional),
            {SOURCE_SYSTEM, SOURCE_MICROPHONE},
        )

    def test_token_overlap_is_deterministic_and_punctuation_tolerant(self):
        self.assertEqual(
            longest_token_overlap(
                ["Привет,", "мир."],
                ["мир", "снова"],
            ),
            1,
        )
        self.assertEqual(longest_token_overlap(["а", "б"], ["в", "г"]), 0)

    def test_word_timestamps_split_system_audio_by_realtime_speaker(self):
        result = RealtimeASRResult(
            text="добрый день коллеги",
            words=(
                RealtimeWord(0.1, 0.4, "добрый"),
                RealtimeWord(0.4, 0.8, "день"),
                RealtimeWord(1.1, 1.5, "коллеги"),
            ),
        )
        diarizer_calls = []

        def diarizer(source, pcm, sample_rate):
            diarizer_calls.append((source, len(pcm), sample_rate))
            return (
                RealtimeSpeakerTurn(0.0, 0.9, "Спикер 1"),
                RealtimeSpeakerTurn(0.9, 2.0, "Спикер 2"),
            )

        session = RealtimeASRSession(
            lambda *_args: result,
            diarizer=diarizer,
            sources=(SOURCE_SYSTEM,),
            window_seconds=2.0,
            overlap_seconds=0.2,
        )
        session.push(SOURCE_SYSTEM, silent_pcm(2.0))

        snapshot = session.process_ready(max_windows=1)

        self.assertEqual(
            [(segment.speaker, segment.text) for segment in snapshot.provisional.values()],
            [("Спикер 1", "добрый день"), ("Спикер 2", "коллеги")],
        )
        self.assertEqual(diarizer_calls, [(SOURCE_SYSTEM, 64_000, SAMPLE_RATE)])

    def test_push_applies_backpressure_without_mutating_buffer(self):
        session = RealtimeASRSession(
            lambda *_args: "",
            window_seconds=0.5,
            overlap_seconds=0.1,
            max_buffer_seconds=1.0,
        )

        with self.assertRaises(BackpressureError):
            session.push(SOURCE_SYSTEM, silent_pcm(1.1))

        self.assertEqual(session.snapshot().buffered_seconds[SOURCE_SYSTEM], 0.0)

    def test_pending_committed_segments_are_bounded_and_drainable(self):
        asr = FakeASR(
            {
                SOURCE_SYSTEM: [
                    "один граница",
                    "граница два",
                    "два три",
                ],
            }
        )
        session = RealtimeASRSession(
            asr,
            window_seconds=1.0,
            overlap_seconds=0.2,
            max_pending_segments=1,
        )
        session.push(SOURCE_SYSTEM, silent_pcm(2.6))

        session.process_ready(max_windows=2)
        with self.assertRaises(BackpressureError):
            session.process_ready(max_windows=1)

        drained = session.drain_committed()
        self.assertEqual([segment.text for segment in drained], ["один"])
        snapshot = session.process_ready(max_windows=1)
        self.assertLessEqual(len(snapshot.committed), 1)

    def test_stop_flushes_partial_window_and_commits_final_text(self):
        asr = FakeASR({SOURCE_MICROPHONE: ["короткая финальная реплика"]})
        session = RealtimeASRSession(asr, window_seconds=1.0, overlap_seconds=0.2)
        session.push(SOURCE_MICROPHONE, silent_pcm(0.5))

        snapshot = session.stop()

        self.assertTrue(snapshot.finalized)
        self.assertEqual(len(asr.calls), 1)
        self.assertEqual(asr.calls[0][1], SAMPLE_RATE)
        self.assertEqual(
            [(segment.source, segment.text) for segment in snapshot.committed],
            [(SOURCE_MICROPHONE, "короткая финальная реплика")],
        )
        self.assertEqual(snapshot.provisional, {})

    def test_stop_does_not_decode_overlap_without_new_audio(self):
        asr = FakeASR({SOURCE_SYSTEM: ["готовая реплика"]})
        session = RealtimeASRSession(asr, window_seconds=1.0, overlap_seconds=0.2)
        session.push(SOURCE_SYSTEM, silent_pcm(1.0))
        session.process_ready(max_windows=1)

        snapshot = session.stop()

        self.assertEqual(len(asr.calls), 1)
        self.assertEqual(snapshot.committed[0].text, "готовая реплика")

    def test_stop_decodes_trailing_audio_and_deduplicates_overlap(self):
        asr = FakeASR(
            {
                SOURCE_SYSTEM: [
                    "первая часть граница",
                    "граница хвост",
                ]
            }
        )
        session = RealtimeASRSession(asr, window_seconds=1.0, overlap_seconds=0.2)
        session.push(SOURCE_SYSTEM, silent_pcm(1.25))
        session.process_ready(max_windows=1)

        snapshot = session.stop()

        self.assertEqual(len(asr.calls), 2)
        self.assertEqual(
            [segment.text for segment in snapshot.committed],
            ["первая часть", "граница хвост"],
        )

    def test_rejects_unknown_source_and_pcm_with_partial_sample(self):
        session = RealtimeASRSession(lambda *_args: "")

        with self.assertRaisesRegex(ValueError, "источник"):
            session.push("speaker", b"\0\0")
        with self.assertRaisesRegex(ValueError, "целое число"):
            session.push(SOURCE_SYSTEM, b"\0")


if __name__ == "__main__":
    unittest.main()
