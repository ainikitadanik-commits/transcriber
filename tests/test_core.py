import json
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from transcriber.core import (
    Segment,
    SpeakerTurn,
    TranscriptionError,
    Word,
    assign_speakers,
    build_document,
    build_txt,
    combine_wav_parts,
    diarize_audio,
    find_recovery_gaps,
    load_model,
    normalize_audio,
    recover_missing_segments,
    resolve_audio_enhancement,
    run,
    transcribe_audio,
    validate_input,
    write_outputs,
)


class CoreTests(unittest.TestCase):
    def test_load_model_reuses_legacy_gigaam_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = root / "application-support" / "gigaam"
            legacy = root / ".cache" / "gigaam"
            legacy.mkdir(parents=True)
            (legacy / "v3_e2e_rnnt.ckpt").write_bytes(b"model")
            (legacy / "v3_e2e_rnnt_tokenizer.model").write_bytes(b"tokenizer")

            with (
                patch.dict(
                    "os.environ",
                    {"TRANSCRIBER_GIGAAM_MODELS_DIR": str(configured)},
                ),
                patch("transcriber.core.Path.home", return_value=root),
                patch("transcriber.core._use_in_memory_audio_for_gigaam"),
                patch("gigaam.load_model", return_value="loaded") as loader,
            ):
                result = load_model("cpu")

        self.assertEqual(result, "loaded")
        self.assertEqual(loader.call_args.kwargs["download_root"], str(legacy))

    def test_webm_and_mp4_are_equal_supported_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("meeting.webm", "meeting.mp4"):
                path = root / name
                path.write_bytes(b"video")
                self.assertEqual(validate_input(path), path.resolve())

    def test_mp3_and_m4a_are_supported_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("meeting.mp3", "meeting.m4a"):
                path = root / name
                path.write_bytes(b"audio")
                self.assertEqual(validate_input(path), path.resolve())

    def test_ffmpeg_normalizes_each_video_format_to_mono_16khz(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension in (".webm", ".mp4"):
                source = root / f"meeting{extension}"
                target = root / f"meeting-{extension[1:]}.wav"
                with patch("subprocess.run") as run_mock:
                    normalize_audio(source, target, "/opt/ffmpeg")
                command = run_mock.call_args.args[0]
                self.assertIn(str(source), command)
                self.assertEqual(command[command.index("-ac") + 1], "1")
                self.assertEqual(command[command.index("-ar") + 1], "16000")
                self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")

    def test_audio_enhancement_adds_safe_filter_chain(self):
        with patch("subprocess.run") as run_mock:
            normalize_audio(
                Path("meeting.m4a"), Path("meeting.wav"), "ffmpeg", True
            )
        command = run_mock.call_args.args[0]
        self.assertIn("-af", command)
        self.assertIn("loudnorm", command[command.index("-af") + 1])

    def test_txt_and_json_contract(self):
        segments = [
            Segment(0.125, 2.5, "Добрый день."),
            Segment(3.0, 5.25, "Начинаем встречу."),
        ]
        txt = build_txt(segments)
        self.assertIn("[00:00:00.125 --> 00:00:02.500] Добрый день.", txt)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "meeting.webm"
            source.write_bytes(b"video")
            from datetime import datetime, timezone

            document = build_document(
                source,
                segments,
                "auto",
                "cpu",
                2,
                True,
                datetime(2026, 7, 15, tzinfo=timezone.utc),
                12.3456,
            )
            txt_path, json_path, docx_path = write_outputs(
                root / "out", "meeting", txt, document
            )
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            docx_created = docx_path.is_file()

        self.assertTrue(txt_path.name.endswith(".txt"))
        self.assertEqual(saved["schema_version"], "1.3")
        self.assertEqual(saved["input"]["format"], "webm")
        self.assertEqual(saved["processing"]["model"], "v3_e2e_rnnt")
        self.assertTrue(saved["processing"]["cpu_fallback_used"])
        self.assertEqual(saved["text"], "Добрый день. Начинаем встречу.")
        self.assertEqual(
            saved["segments"][0],
            {
                "start": 0.125,
                "end": 2.5,
                "speaker": None,
                "text": "Добрый день.",
            },
        )
        self.assertTrue(docx_created)

    def test_repeated_output_stem_preserves_each_result_set(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            document = {"schema_version": "1.3", "segments": []}

            with patch(
                "transcriber.core.write_docx",
                side_effect=lambda path, _document: path.write_bytes(b"docx"),
            ):
                first = write_outputs(output_dir, "C1-speakers", "первый", document)
                second = write_outputs(output_dir, "C1-speakers", "второй", document)
                third = write_outputs(output_dir, "C1-speakers", "третий", document)

            self.assertEqual(
                [[path.name for path in result] for result in (first, second, third)],
                [
                    ["C1-speakers.txt", "C1-speakers.json", "C1-speakers.docx"],
                    [
                        "C1-speakers-2.txt",
                        "C1-speakers-2.json",
                        "C1-speakers-2.docx",
                    ],
                    [
                        "C1-speakers-3.txt",
                        "C1-speakers-3.json",
                        "C1-speakers-3.docx",
                    ],
                ],
            )
            self.assertEqual(first[0].read_text(), "первый")
            self.assertEqual(second[0].read_text(), "второй")
            self.assertEqual(third[0].read_text(), "третий")

    def test_auto_audio_enhancement_uses_measured_loudness(self):
        result = type(
            "Result",
            (),
            {"stderr": "Summary:\n  I:         -24.7 LUFS", "returncode": 0},
        )()
        with patch("subprocess.run", return_value=result):
            enabled, loudness = resolve_audio_enhancement(
                "auto", Path("meeting.m4a"), "ffmpeg"
            )
        self.assertTrue(enabled)
        self.assertEqual(loudness, -24.7)

    def test_wav_parts_are_combined_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = []
            for index, seconds in enumerate((1, 2), start=1):
                path = root / f"part-{index}.wav"
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(16000)
                    audio.writeframes((array("h", [index * 1000]) * (seconds * 16000)).tobytes())
                parts.append(path)
            combined = root / "combined.wav"
            combine_wav_parts(parts, combined)
            with wave.open(str(combined), "rb") as audio:
                self.assertEqual(audio.getnframes(), 3 * 16000)

    def test_longform_uses_safe_batch_size(self):
        class RawSegment:
            start = 1.0
            end = 2.0
            text = "  Текст.  "

        class FakeModel:
            def transcribe_longform(self, path, fr_batch_size, word_timestamps=False):
                self.path = path
                self.batch_size = fr_batch_size
                self.word_timestamps = word_timestamps
                return [RawSegment()]

        model = FakeModel()
        result = transcribe_audio(
            Path("audio.wav"), "cpu", 2, model_loader=lambda device: model
        )
        self.assertEqual(model.batch_size, 2)
        self.assertFalse(model.word_timestamps)
        self.assertEqual(result, [Segment(1.0, 2.0, "Текст.")])

    def test_missing_hf_token_has_actionable_error(self):
        class FakeModel:
            def transcribe_longform(self, path, fr_batch_size, word_timestamps=False):
                raise RuntimeError(
                    "Model pyannote/segmentation-3.0 was not found locally, "
                    "and no HF_TOKEN was provided to download it."
                )

        with self.assertRaisesRegex(TranscriptionError, "pyannote"):
            transcribe_audio(
                Path("audio.wav"),
                "cpu",
                2,
                model_loader=lambda device: FakeModel(),
            )

    def test_speaker_turns_split_words_and_preserve_punctuation(self):
        segments = [
            Segment(
                0.0,
                4.0,
                "Добрый день. Начинаем.",
                words=(
                    Word(0.0, 0.7, "Добрый"),
                    Word(0.7, 1.2, "день."),
                    Word(2.1, 3.0, "Начинаем"),
                    Word(3.0, 3.2, "."),
                ),
            )
        ]
        turns = [
            SpeakerTurn(0.0, 1.5, "SPEAKER_01"),
            SpeakerTurn(1.5, 4.0, "SPEAKER_00"),
        ]

        result = assign_speakers(segments, turns)

        self.assertEqual(result[0].speaker, "Спикер 1")
        self.assertEqual(result[0].text, "Добрый день.")
        self.assertEqual(result[1].speaker, "Спикер 2")
        self.assertEqual(result[1].text, "Начинаем.")
        self.assertIn("Спикер 1: Добрый день.", build_txt(result))

    def test_speaker_count_is_passed_to_diarization_pipeline(self):
        class Annotation:
            def itertracks(self, yield_label=False):
                return []

        class Output:
            exclusive_speaker_diarization = Annotation()

        class Pipeline:
            def __call__(self, audio, **options):
                self.audio = audio
                self.options = options
                return Output()

        pipeline = Pipeline()
        with patch(
            "transcriber.core.pyannote_audio",
            return_value={"waveform": "local", "sample_rate": 16000},
        ):
            diarize_audio(
                Path("audio.wav"),
                "cpu",
                num_speakers=3,
                pipeline_loader=lambda _device: pipeline,
            )
        self.assertEqual(pipeline.options, {"num_speakers": 3})
        self.assertEqual(pipeline.audio["waveform"], "local")

    def test_gap_recovery_transcribes_only_missing_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "audio.wav"
            samples = array("h", [1200]) * (8 * 16000)
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(samples.tobytes())

            existing = [Segment(0.0, 2.0, "До"), Segment(6.0, 8.0, "После")]
            self.assertEqual(find_recovery_gaps(existing, 8.0), [(2.0, 6.0)])

            class RawWord:
                start = 1.0
                end = 1.7
                text = "Пропущено."

            class Result:
                words = [RawWord()]

            class Model:
                def transcribe(self, path, word_timestamps=False):
                    self.word_timestamps = word_timestamps
                    return Result()

            model = Model()
            with patch("transcriber.core.extract_audio_chunk"):
                recovered = recover_missing_segments(
                    model, audio_path, existing, "ffmpeg"
                )

        self.assertTrue(model.word_timestamps)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].text, "Пропущено.")

    def test_multi_part_run_has_continuous_offsets_and_combined_outputs(self):
        class RawSegment:
            start = 0.0
            end = 3.0
            text = "Вся встреча."

        class Model:
            def transcribe_longform(self, path, fr_batch_size, word_timestamps=False):
                return [RawSegment()]

        progress_updates = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / "part-one.m4a", root / "part-two.mp3"]
            for source in sources:
                source.write_bytes(b"audio")

            def fake_normalize(source, target, _ffmpeg, _enhance=False):
                seconds = 1 if source.suffix == ".m4a" else 2
                with wave.open(str(target), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(16000)
                    audio.writeframes(
                        (array("h", [1000]) * (seconds * 16000)).tobytes()
                    )

            with (
                patch("transcriber.core.require_ffmpeg", return_value="ffmpeg"),
                patch("transcriber.core.choose_device", return_value="cpu"),
                patch("transcriber.core.normalize_audio", side_effect=fake_normalize),
            ):
                txt_path, json_path, docx_path, _, _ = run(
                    sources,
                    root / "out",
                    recover_gaps=False,
                    enhancement_mode="off",
                    model_loader=lambda _device: Model(),
                    progress_callback=lambda progress, stage, message: progress_updates.append(
                        (progress, stage, message)
                    ),
                )

            saved = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(txt_path.name, "part-one-combined.txt")
        self.assertEqual(docx_path.name, "part-one-combined.docx")
        self.assertEqual(saved["input"]["format"], "multi_part")
        self.assertEqual(saved["input"]["parts"][0]["start"], 0.0)
        self.assertEqual(saved["input"]["parts"][0]["end"], 1.0)
        self.assertEqual(saved["input"]["parts"][1]["start"], 1.0)
        self.assertEqual(saved["input"]["parts"][1]["end"], 3.0)
        self.assertIn("transcribing", [update[1] for update in progress_updates])
        self.assertEqual(progress_updates[-1][0], 97)

    def test_diarization_run_creates_separate_speaker_outputs(self):
        class RawWord:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text

        class RawSegment:
            start = 0.0
            end = 2.0
            text = "Добрый день."
            words = [RawWord(0.0, 0.8, "Добрый"), RawWord(0.8, 1.4, "день.")]

        class FakeModel:
            def transcribe_longform(self, path, fr_batch_size, word_timestamps=False):
                self.word_timestamps = word_timestamps
                return [RawSegment()]

        class Turn:
            start = 0.0
            end = 2.0

        class Annotation:
            def itertracks(self, yield_label=False):
                return [(Turn(), None, "SPEAKER_00")]

        class Output:
            exclusive_speaker_diarization = Annotation()

        class FakePipeline:
            def __call__(self, audio, **options):
                return Output()

        model = FakeModel()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "meeting.m4a"
            source.write_bytes(b"audio")

            def fake_normalize(_source, target, _ffmpeg, _enhance=False):
                with wave.open(str(target), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(16000)
                    audio.writeframes((array("h", [1000]) * (2 * 16000)).tobytes())

            with (
                patch("transcriber.core.require_ffmpeg", return_value="ffmpeg"),
                patch("transcriber.core.choose_device", return_value="cpu"),
                patch("transcriber.core.normalize_audio", side_effect=fake_normalize),
                patch(
                    "transcriber.core.pyannote_audio",
                    return_value={"waveform": "local", "sample_rate": 16000},
                ),
            ):
                txt_path, json_path, docx_path, _, _ = run(
                    source,
                    root / "out",
                    diarization=True,
                    recover_gaps=False,
                    enhancement_mode="off",
                    model_loader=lambda _device: model,
                    diarization_loader=lambda _device: FakePipeline(),
                )

            saved = json.loads(json_path.read_text(encoding="utf-8"))
            txt_content = txt_path.read_text(encoding="utf-8")

        self.assertTrue(model.word_timestamps)
        self.assertEqual(txt_path.name, "meeting-speakers.txt")
        self.assertEqual(json_path.name, "meeting-speakers.json")
        self.assertEqual(docx_path.name, "meeting-speakers.docx")
        self.assertIn("Спикер 1: Добрый день.", txt_content)
        self.assertTrue(saved["processing"]["diarization"]["enabled"])
        self.assertEqual(saved["processing"]["diarization"]["num_speakers"], 1)


if __name__ == "__main__":
    unittest.main()
