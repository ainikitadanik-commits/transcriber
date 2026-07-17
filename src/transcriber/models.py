from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


SEGMENTATION_MODEL = "pyannote/segmentation-3.0"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"


def data_dir() -> Path:
    configured = os.getenv("TRANSCRIBER_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "Транскрибатор"


def configure_storage() -> Path:
    root = data_dir()
    os.environ["HF_HOME"] = str(root / "models" / "huggingface")
    os.environ["TRANSCRIBER_GIGAAM_MODELS_DIR"] = str(root / "models" / "gigaam")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    for directory in (root / "input", root / "output", root / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
    return root


def local_snapshot(model_id: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=model_id, local_files_only=True)


def prepare_pyannote_models(
    token: str | None,
    diarization: bool,
    progress: Callable[[int, str, str], None] | None = None,
) -> None:
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    models = [SEGMENTATION_MODEL]
    if diarization:
        models.append(DIARIZATION_MODEL)

    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    if token:
        os.environ["HF_TOKEN"] = token

    try:
        for index, model_id in enumerate(models, start=1):
            if progress:
                progress(
                    5 + index * 4,
                    "downloading_models",
                    "Проверяем локальные модели…",
                )
            try:
                snapshot_download(repo_id=model_id, local_files_only=True)
            except LocalEntryNotFoundError:
                if not token:
                    raise RuntimeError(
                        "Модель pyannote ещё не загружена. Примите условия "
                        "Hugging Face и введите личный Read-токен."
                    )
                snapshot_download(repo_id=model_id, token=token)
    finally:
        os.environ.pop("HF_TOKEN", None)

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
