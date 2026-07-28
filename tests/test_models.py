import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huggingface_hub.errors import LocalEntryNotFoundError

from transcriber.core import TranscriptionError, load_model
from transcriber.models import configure_storage, prepare_pyannote_models


class ModelTests(unittest.TestCase):
    def tearDown(self):
        for name in (
            "TRANSCRIBER_DATA_DIR",
            "TRANSCRIBER_GIGAAM_MODELS_DIR",
            "HF_HOME",
            "HF_TOKEN",
            "HF_HUB_OFFLINE",
            "PYANNOTE_METRICS_ENABLED",
            "TRANSFORMERS_OFFLINE",
        ):
            os.environ.pop(name, None)

    def test_configure_storage_uses_user_writable_root(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ["TRANSCRIBER_DATA_DIR"] = directory
            root = configure_storage()
            self.assertEqual(root, Path(directory))
            self.assertTrue((root / "input").is_dir())
            self.assertTrue((root / "output").is_dir())
            self.assertEqual(
                os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"],
                str(root / "models" / "gigaam"),
            )
            self.assertEqual(os.environ["PYANNOTE_METRICS_ENABLED"], "0")

    def test_configure_storage_preserves_explicit_gigaam_models_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = (
                root / "App" / "Contents" / "Resources" / "models" / "gigaam"
            )
            os.environ["TRANSCRIBER_DATA_DIR"] = str(root / "clean-user")
            os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"] = str(explicit)
            os.environ["PYANNOTE_METRICS_ENABLED"] = "1"

            configure_storage()

            self.assertEqual(
                os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"],
                str(explicit),
            )
            self.assertEqual(os.environ["PYANNOTE_METRICS_ENABLED"], "0")

    def test_explicit_bundled_gigaam_pairs_load_on_clean_account(self):
        for model_name in ("v3_e2e_rnnt", "v3_e2e_ctc"):
            with (
                self.subTest(model=model_name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                bundled = (
                    root / "App" / "Contents" / "Resources" / "models" / "gigaam"
                )
                bundled.mkdir(parents=True)
                (bundled / f"{model_name}.ckpt").write_bytes(b"model")
                (bundled / f"{model_name}_tokenizer.model").write_bytes(b"tokenizer")
                os.environ["TRANSCRIBER_DATA_DIR"] = str(root / "clean-user")
                os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"] = str(bundled)

                configure_storage()
                with (
                    patch("transcriber.core.Path.home", return_value=root),
                    patch("transcriber.core._use_in_memory_audio_for_gigaam"),
                    patch("gigaam.load_model", return_value="loaded") as loader,
                ):
                    result = load_model("cpu", model_name)

                self.assertEqual(result, "loaded")
                self.assertEqual(
                    loader.call_args.kwargs["download_root"],
                    str(bundled),
                )

    def test_explicit_bundled_gigaam_requires_complete_pair(self):
        for model_name, present_file in (
            ("v3_e2e_rnnt", "v3_e2e_rnnt.ckpt"),
            ("v3_e2e_ctc", "v3_e2e_ctc_tokenizer.model"),
        ):
            with (
                self.subTest(model=model_name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                bundled = (
                    root / "App" / "Contents" / "Resources" / "models" / "gigaam"
                )
                bundled.mkdir(parents=True)
                (bundled / present_file).write_bytes(b"partial")
                os.environ["TRANSCRIBER_DATA_DIR"] = str(root / "clean-user")
                os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"] = str(bundled)

                configure_storage()
                with (
                    patch("transcriber.core.Path.home", return_value=root),
                    patch("transcriber.core._use_in_memory_audio_for_gigaam"),
                ):
                    with self.assertRaisesRegex(
                        TranscriptionError,
                        "Локальные веса GigaAM не найдены",
                    ):
                        load_model("cpu", model_name)

    def test_model_download_finishes_before_offline_mode(self):
        calls = []

        def snapshot_download(**options):
            calls.append(dict(options))
            if options.get("local_files_only"):
                raise LocalEntryNotFoundError("missing")
            return "/local/model"

        with patch("huggingface_hub.snapshot_download", side_effect=snapshot_download):
            prepare_pyannote_models("secret", diarization=True)

        self.assertEqual(len(calls), 4)
        self.assertNotIn("HF_TOKEN", os.environ)
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
        self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")


if __name__ == "__main__":
    unittest.main()
