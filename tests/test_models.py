import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huggingface_hub.errors import LocalEntryNotFoundError

from transcriber.models import configure_storage, prepare_pyannote_models


class ModelTests(unittest.TestCase):
    def tearDown(self):
        for name in (
            "TRANSCRIBER_DATA_DIR",
            "TRANSCRIBER_GIGAAM_MODELS_DIR",
            "HF_HOME",
            "HF_TOKEN",
            "HF_HUB_OFFLINE",
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
