from __future__ import annotations

import argparse
import os
import re
import subprocess
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

from . import __version__
from .core import (
    ENHANCEMENT_MODES,
    MODEL_NAME,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_MODELS,
    TranscriptionError,
    run,
)
from .models import configure_storage, data_dir, prepare_pyannote_models
from .realtime import capture_manager
from .realtime_service import RealtimeTranscriptionService


DATA_DIR = data_dir()
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
realtime_service = RealtimeTranscriptionService(capture_manager, OUTPUT_DIR)

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024 * 1024

_lock = threading.Lock()
_job: dict[str, Any] = {"status": "idle"}
_default_instance_id = uuid.uuid4().hex


def _runtime_identity() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product": "transcriber",
        "bundle_id": "com.ainikitadanik.transcriber",
        "version": __version__,
        "build_id": os.getenv("TRANSCRIBER_BUILD_ID") or __version__,
        "instance_id": os.getenv("TRANSCRIBER_INSTANCE_ID")
        or _default_instance_id,
        "pid": os.getpid(),
    }


def _safe_filename(raw_name: str) -> str:
    name = Path(raw_name).name.strip()
    name = re.sub(r"[^\w.()\- ]+", "_", name, flags=re.UNICODE)
    return name or "recording"


def _snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_job)


def _update(**values: Any) -> None:
    with _lock:
        _job.update(values)


def _friendly_error(error: Exception) -> str:
    details = str(error)
    if any(
        marker in details
        for marker in ("ConnectError", "Network is down", "Connection error")
    ):
        return (
            "Не удалось подключиться к Hugging Face для первой загрузки модели. "
            "Проверьте интернет и перезапустите транскрибатор через файл "
            "«Запустить транскрибатор.command», затем повторите попытку."
        )
    if any(
        marker in details
        for marker in ("GatedRepoError", "401 Client Error", "403 Client Error")
    ):
        return (
            "Hugging Face не разрешил скачать модель pyannote. Убедитесь, что "
            "вы приняли условия pyannote/segmentation-3.0, а для разделения "
            "по спикерам — также pyannote/speaker-diarization-community-1, "
            "и вставили Read-токен."
        )
    return f"Ошибка GigaAM: {details}"


def _process(
    job_id: str,
    input_paths: list[Path],
    device: str,
    token: str | None,
    diarization: bool,
    speaker_count: int | None,
    recover_gaps: bool,
    enhancement_mode: str,
    model_name: str,
) -> None:
    def update_progress(progress: int, stage: str, message: str) -> None:
        _update(progress=progress, stage=stage, message=message)

    try:
        if diarization:
            prepare_pyannote_models(token, diarization, update_progress)
        os.environ.pop("HF_TOKEN", None)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        message = (
            "Распознаём речь и разделяем спикеров…"
            if diarization
            else "Распознаём речь и расставляем таймкоды…"
        )
        _update(
            status="running",
            message=message,
            diarization=diarization,
            gap_recovery=recover_gaps,
            model=model_name,
            parts=len(input_paths),
            progress=2,
            stage="preparing",
        )
        txt_path, json_path, docx_path, used_device, fallback = run(
            input_path=input_paths,
            output_dir=OUTPUT_DIR,
            requested_device=device,
            batch_size=2,
            diarization=diarization,
            speaker_count=speaker_count,
            recover_gaps=recover_gaps,
            enhancement_mode=enhancement_mode,
            model_name=model_name,
            local_windowing=not diarization,
            progress_callback=update_progress,
        )
        _update(
            status="done",
            message="Транскрипция готова",
            progress=100,
            stage="done",
            device=used_device,
            fallback=fallback,
            txt_name=txt_path.name,
            json_name=json_path.name,
            docx_name=docx_path.name,
        )
    except TranscriptionError as error:
        _update(status="error", message=str(error))
    except Exception as error:
        _update(status="error", message=_friendly_error(error))
    finally:
        os.environ.pop("HF_TOKEN", None)
        _update(id=job_id)


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="Файл слишком большой для загрузки."), 413


@app.post("/api/transcribe")
def start_transcription():
    current = _snapshot()
    if current.get("status") in {"uploading", "running"}:
        return jsonify(error="Дождитесь завершения текущей транскрипции."), 409

    uploaded_files = [
        uploaded
        for uploaded in (request.files.getlist("files") or request.files.getlist("file"))
        if uploaded.filename
    ]
    if not uploaded_files:
        return jsonify(error="Выберите файл для транскрибации."), 400

    filenames = [_safe_filename(uploaded.filename) for uploaded in uploaded_files]
    if any(Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS for filename in filenames):
        return jsonify(
            error="Поддерживаются WEBM, MP4, MP3, M4A и другие аудиоформаты."
        ), 400

    device = request.form.get("device", "auto")
    if device not in {"auto", "mps", "cpu"}:
        return jsonify(error="Некорректный режим устройства."), 400

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    _update(
        id=job_id,
        status="uploading",
        message=f"Сохраняем части встречи: {len(uploaded_files)}…",
        progress=1,
        stage="uploading",
    )
    job_input_dir = INPUT_DIR / job_id
    job_input_dir.mkdir(parents=True, exist_ok=True)
    input_paths: list[Path] = []
    try:
        for index, (uploaded, filename) in enumerate(
            zip(uploaded_files, filenames), start=1
        ):
            part_dir = job_input_dir / f"{index:03}"
            part_dir.mkdir()
            input_path = part_dir / filename
            uploaded.save(input_path)
            input_paths.append(input_path)
    except Exception as error:
        _update(status="error", message=f"Не удалось сохранить файл: {error}")
        return jsonify(error=_snapshot()["message"]), 500

    token = request.form.get("hf_token", "").strip() or None
    diarization = request.form.get("diarization") == "on"
    recover_gaps = request.form.get("recover_gaps") == "on"
    enhancement_mode = request.form.get("audio_enhancement", "auto")
    if enhancement_mode not in ENHANCEMENT_MODES:
        return jsonify(error="Некорректный режим тихих голосов."), 400
    model_name = request.form.get("model", MODEL_NAME)
    if model_name not in SUPPORTED_MODELS:
        return jsonify(error="Некорректная модель GigaAM."), 400
    speaker_count_raw = request.form.get("speaker_count", "").strip()
    try:
        speaker_count = int(speaker_count_raw) if speaker_count_raw else None
    except ValueError:
        return jsonify(error="Некорректное число участников."), 400
    if speaker_count is not None and not 1 <= speaker_count <= 10:
        return jsonify(error="Число участников должно быть от 1 до 10."), 400
    if not diarization:
        speaker_count = None
    worker = threading.Thread(
        target=_process,
        args=(
            job_id,
            input_paths,
            device,
            token,
            diarization,
            speaker_count,
            recover_gaps,
            enhancement_mode,
            model_name,
        ),
        daemon=True,
    )
    worker.start()
    return jsonify(id=job_id), 202


@app.get("/api/status/<job_id>")
def status(job_id: str):
    current = _snapshot()
    if current.get("id") != job_id:
        return jsonify(error="Задача не найдена."), 404
    return jsonify(current)


@app.get("/files/<path:filename>")
def result_file(filename: str):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@app.post("/api/open-folder/<folder_name>")
def open_folder(folder_name: str):
    folders = {"input": INPUT_DIR, "output": OUTPUT_DIR}
    folder = folders.get(folder_name)
    if folder is None:
        return jsonify(error="Неизвестная папка."), 404
    folder.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["open", str(folder)], check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        return jsonify(error=f"Не удалось открыть папку: {error}"), 500
    return jsonify(message="Папка открыта в Finder.")


@app.get("/api/health")
def health():
    return jsonify(_runtime_identity())


@app.get("/api/realtime/status")
def realtime_status():
    return jsonify(realtime_service.snapshot())


@app.post("/api/realtime/start")
def realtime_start():
    payload = request.get_json(silent=True) or {}
    include_microphone = payload.get("include_microphone", False)
    diarization = payload.get("diarization", False)
    hf_token = payload.get("hf_token") or None
    if not isinstance(include_microphone, bool):
        return jsonify(error="Параметр include_microphone должен быть boolean."), 400
    if not isinstance(diarization, bool):
        return jsonify(error="Параметр diarization должен быть boolean."), 400
    if hf_token is not None and not isinstance(hf_token, str):
        return jsonify(error="Параметр hf_token должен быть строкой."), 400
    try:
        return jsonify(
            realtime_service.start(
                include_microphone=include_microphone,
                diarization=diarization,
                hf_token=hf_token.strip() if hf_token else None,
            )
        ), 202
    except RuntimeError as error:
        return jsonify(error=str(error)), 409


@app.post("/api/realtime/stop")
def realtime_stop():
    return jsonify(realtime_service.stop()), 202


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Локальный интерфейс транскрибатора")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_storage()
    host = "127.0.0.1"
    url = f"http://{host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Транскрибатор открыт: {url}")
    app.run(host=host, port=args.port, debug=False, use_reloader=False)
    return 0
