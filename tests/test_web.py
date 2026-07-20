import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import transcriber.web as web


class ImmediateThread:
    def __init__(self, target, args, daemon):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class WebTests(unittest.TestCase):
    def setUp(self):
        web._job.clear()
        web._job.update(status="idle")
        self.client = web.app.test_client()

    def test_home_page_contains_upload_ui(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Перетащите запись сюда", response.get_data(as_text=True))
        self.assertIn("Разделить по спикерам", response.get_data(as_text=True))
        self.assertIn(".m4a", response.get_data(as_text=True))
        self.assertIn("Проверять пропуски повторно", response.get_data(as_text=True))
        self.assertIn("RNNT", response.get_data(as_text=True))
        self.assertIn("Добавить следующую часть", response.get_data(as_text=True))
        self.assertIn('value="auto"', response.get_data(as_text=True))
        self.assertIn("Скачать DOCX", response.get_data(as_text=True))
        self.assertIn("progress-percent", response.get_data(as_text=True))
        self.assertIn("Ориентировочный прогресс", response.get_data(as_text=True))
        self.assertIn("Открыть записи", response.get_data(as_text=True))
        self.assertIn("Открыть транскрипции", response.get_data(as_text=True))

    def test_open_folder_uses_finder_for_whitelisted_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            with (
                patch.object(web, "INPUT_DIR", input_dir),
                patch.object(web.subprocess, "run") as run_mock,
            ):
                response = self.client.post("/api/open-folder/input")

        self.assertEqual(response.status_code, 200)
        run_mock.assert_called_once_with(
            ["open", str(input_dir)], check=True, capture_output=True, text=True
        )

    def test_open_folder_rejects_unknown_location(self):
        with patch.object(web.subprocess, "run") as run_mock:
            response = self.client.post("/api/open-folder/models")

        self.assertEqual(response.status_code, 404)
        run_mock.assert_not_called()

    def test_rejects_unsupported_file(self):
        response = self.client.post(
            "/api/transcribe",
            data={"file": (io.BytesIO(b"data"), "notes.docx")},
        )
        self.assertEqual(response.status_code, 400)

    def test_network_failure_has_actionable_russian_message(self):
        message = web._friendly_error(
            RuntimeError("Got: ConnectError: [Errno 50] Network is down")
        )
        self.assertIn("Не удалось подключиться к Hugging Face", message)
        self.assertIn("Запустить транскрибатор.command", message)

    def test_gated_model_failure_explains_access_steps(self):
        message = web._friendly_error(RuntimeError("GatedRepoError: 403 Client Error"))
        self.assertIn("приняли условия", message)
        self.assertIn("Read-токен", message)

    def test_upload_runs_pipeline_and_exposes_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = root / "output"
            output_dir.mkdir()
            txt = output_dir / "meeting.txt"
            json_file = output_dir / "meeting.json"
            docx = output_dir / "meeting.docx"
            txt.write_text("result", encoding="utf-8")
            json_file.write_text("{}", encoding="utf-8")
            docx.write_bytes(b"docx")

            with (
                patch.object(web, "INPUT_DIR", input_dir),
                patch.object(web, "OUTPUT_DIR", output_dir),
                patch.object(web.threading, "Thread", ImmediateThread),
                patch.object(web, "prepare_pyannote_models") as prepare_mock,
                patch.object(
                    web, "run", return_value=(txt, json_file, docx, "cpu", False)
                ) as run_mock,
            ):
                response = self.client.post(
                    "/api/transcribe",
                    data={
                        "files": [
                            (io.BytesIO(b"video-1"), "meeting-1.webm"),
                            (io.BytesIO(b"video-2"), "meeting-2.m4a"),
                        ],
                        "device": "auto",
                        "hf_token": "secret-not-saved",
                        "diarization": "on",
                        "speaker_count": "3",
                        "recover_gaps": "on",
                        "audio_enhancement": "auto",
                        "model": "v3_e2e_ctc",
                    },
                )

            self.assertEqual(response.status_code, 202)
            job_id = response.get_json()["id"]
            status = self.client.get(f"/api/status/{job_id}").get_json()
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["txt_name"], "meeting.txt")
            self.assertEqual(status["docx_name"], "meeting.docx")
            self.assertEqual(status["progress"], 100)
            self.assertEqual(status["stage"], "done")
            self.assertTrue(status["diarization"])
            self.assertEqual(status["parts"], 2)
            self.assertNotIn("secret-not-saved", repr(status))
            self.assertEqual(run_mock.call_args.kwargs["speaker_count"], 3)
            self.assertTrue(run_mock.call_args.kwargs["recover_gaps"])
            self.assertEqual(run_mock.call_args.kwargs["enhancement_mode"], "auto")
            self.assertEqual(run_mock.call_args.kwargs["model_name"], "v3_e2e_ctc")
            self.assertTrue(callable(run_mock.call_args.kwargs["progress_callback"]))
            self.assertEqual(len(run_mock.call_args.kwargs["input_path"]), 2)
            prepare_mock.assert_called_once()
            self.assertNotIn("HF_TOKEN", web.os.environ)
            self.assertEqual(web.os.environ["HF_HUB_OFFLINE"], "1")


if __name__ == "__main__":
    unittest.main()
