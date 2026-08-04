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
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Перетащите запись сюда", html)
        self.assertIn("Разделить по спикерам", html)
        self.assertIn(".m4a", html)
        self.assertIn("Проверять пропуски повторно", html)
        self.assertIn("RNNT", html)
        self.assertIn("Добавить следующую часть", html)
        self.assertIn('value="auto"', html)
        self.assertIn("Скачать DOCX", html)
        self.assertIn("progress-percent", html)
        self.assertIn("Ориентировочный прогресс", html)
        self.assertIn("Открыть записи", html)
        self.assertIn("Открыть транскрипции", html)
        self.assertIn("Из файла", html)
        self.assertIn("Рилтайм", html)
        self.assertIn("Транскрибация в реальном времени", html)
        self.assertIn("transcriber-logo.png", html)
        self.assertIn("распознаётся локально", html)
        self.assertIn("Живой текст", html)
        self.assertIn("Начать встречу", html)
        self.assertIn("<small>Скоро</small>", html)
        self.assertNotIn("пока планируется", html)
        self.assertNotIn("Только захват", html)
        self.assertIn('id="live-start"', html)
        self.assertIn('id="live-pause"', html)
        self.assertIn('id="live-stop"', html)
        self.assertIn('id="live-timer"', html)
        self.assertIn('id="live-transcript-content"', html)
        self.assertIn('id="live-downloads"', html)
        self.assertIn('id="live-txt-link"', html)
        self.assertIn('id="live-json-link"', html)
        self.assertIn('id="live-docx-link"', html)
        self.assertIn("Системный звук: ожидаем", html)
        self.assertIn("Микрофон: выключен", html)
        self.assertIn('id="live-include-microphone"', html)
        self.assertIn("mute внутри ВКС нельзя определить универсально", html)
        self.assertIn("PCM 16 кГц", html)
        self.assertIn("встреча продолжит распознаваться в фоне", html)

    def test_ui_preserves_accessible_contract_and_responsive_guards(self):
        root = Path(__file__).resolve().parents[1]
        html = self.client.get("/").get_data(as_text=True)
        css = (root / "src/transcriber/web/static/app.css").read_text()
        javascript = (root / "src/transcriber/web/static/app.js").read_text()

        self.assertIn('role="tablist"', html)
        self.assertIn('role="tab"', html)
        self.assertIn('role="tabpanel"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('id="status-message" role="status" aria-live="polite" aria-atomic="true"', html)
        self.assertNotIn('id="status" aria-live=', html)
        self.assertIn('name="files"', html)
        self.assertIn('name="device"', html)
        self.assertIn('name="model"', html)
        self.assertIn('name="hf_token"', html)
        self.assertIn('name="recover_gaps"', html)
        self.assertIn('name="audio_enhancement"', html)
        self.assertIn('name="diarization"', html)
        self.assertIn('name="speaker_count"', html)

        self.assertIn("--color-bg:", css)
        self.assertIn("--gradient-primary:", css)
        self.assertIn("--radius-page-card:", css)
        self.assertIn(".file-name-prefix", css)
        self.assertIn(".file-name-tail", css)
        self.assertIn("minmax(0, 1fr)", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

        self.assertIn("function splitFilename", javascript)
        self.assertIn("const baseCharacters = Array.from(base)", javascript)
        self.assertIn("function setTextIfChanged", javascript)
        self.assertIn('title.setAttribute("aria-label", filename)', javascript)
        self.assertIn('title.title = filename', javascript)
        self.assertIn('submitLabel.textContent = loading ? "Транскрибируем…"', javascript)
        self.assertIn('livePause.disabled = true', javascript)
        self.assertIn("function renderRealtimeTranscript", javascript)
        self.assertIn("state.segments", javascript)
        self.assertIn("state.provisional", javascript)
        self.assertIn("realtimeSourceLabels", javascript)
        self.assertIn("liveDownloads.classList.toggle", javascript)
        self.assertIn("encodeURIComponent(name)", javascript)
        self.assertIn('window.confirm("Завершить встречу', javascript)
        self.assertIn('document.addEventListener("visibilitychange"', javascript)
        self.assertIn('window.addEventListener("focus", refreshRealtimeStatus)', javascript)
        self.assertNotIn('addEventListener("pagehide"', javascript)
        self.assertNotIn('addEventListener("beforeunload"', javascript)

    def test_realtime_status_exposes_capture_state(self):
        with patch.object(
            web.realtime_service,
            "snapshot",
            return_value={
                "status": "idle",
                "available": True,
                "asr_status": "idle",
                "segments": [],
            },
        ):
            response = self.client.get("/api/realtime/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["available"])

    def test_realtime_start_and_stop_use_local_capture_manager(self):
        with (
            patch.object(
                web.realtime_service,
                "start",
                return_value={
                    "status": "starting",
                    "available": True,
                    "asr_status": "loading",
                },
            ) as start_mock,
            patch.object(
                web.realtime_service,
                "stop",
                return_value={
                    "status": "stopping",
                    "available": True,
                    "asr_status": "finalizing",
                },
            ) as stop_mock,
        ):
            start_response = self.client.post("/api/realtime/start")
            stop_response = self.client.post("/api/realtime/stop")

        self.assertEqual(start_response.status_code, 202)
        self.assertEqual(stop_response.status_code, 202)
        start_mock.assert_called_once_with(
            include_microphone=False, diarization=False, hf_token=None
        )
        stop_mock.assert_called_once_with()

    def test_realtime_start_can_explicitly_include_microphone(self):
        with patch.object(
            web.realtime_service,
            "start",
            return_value={"status": "starting", "asr_status": "loading"},
        ) as start_mock:
            response = self.client.post(
                "/api/realtime/start",
                json={"include_microphone": True},
            )

        self.assertEqual(response.status_code, 202)
        start_mock.assert_called_once_with(
            include_microphone=True, diarization=False, hf_token=None
        )

    def test_realtime_start_enables_local_speaker_diarization(self):
        with patch.object(
            web.realtime_service,
            "start",
            return_value={"status": "starting", "asr_status": "loading"},
        ) as start_mock:
            response = self.client.post(
                "/api/realtime/start",
                json={"diarization": True, "hf_token": "  hf_test  "},
            )

        self.assertEqual(response.status_code, 202)
        start_mock.assert_called_once_with(
            include_microphone=False,
            diarization=True,
            hf_token="hf_test",
        )

    def test_realtime_start_rejects_non_boolean_microphone_option(self):
        response = self.client.post(
            "/api/realtime/start",
            json={"include_microphone": "yes"},
        )

        self.assertEqual(response.status_code, 400)

    def test_realtime_start_returns_actionable_error(self):
        with patch.object(
            web.realtime_service,
            "start",
            side_effect=RuntimeError("Помощник захвата не собран."),
        ):
            response = self.client.post("/api/realtime/start")

        self.assertEqual(response.status_code, 409)
        self.assertIn("не собран", response.get_json()["error"])

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
