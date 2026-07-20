from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .models import data_dir


def capture_helper_path() -> Path:
    configured = os.getenv("TRANSCRIBER_CAPTURE_HELPER")
    if configured:
        return Path(configured).expanduser()

    installed = data_dir() / "bin" / "realtime-capture"
    if installed.is_file():
        return installed

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "realtime-capture"

    return Path(__file__).resolve().parents[2] / "build" / "realtime-capture"


class RealtimeCaptureManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._state: dict[str, Any] = {
            "status": "idle",
            "message": "Готово к запуску.",
            "system_audio": False,
            "microphone": False,
        }
        self._started_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        helper = capture_helper_path()
        with self._lock:
            state = dict(self._state)
            started_at = self._started_at
        state["available"] = helper.is_file() and os.access(helper, os.X_OK)
        state["elapsed_seconds"] = (
            max(0, int(time.monotonic() - started_at)) if started_at else 0
        )
        return state

    def start(self) -> dict[str, Any]:
        helper = capture_helper_path()
        if not helper.is_file() or not os.access(helper, os.X_OK):
            raise RuntimeError(
                "Помощник захвата не собран. Выполните "
                "scripts/build_realtime_helper.sh и перезапустите транскрибатор."
            )

        with self._lock:
            if self._process and self._process.poll() is None:
                raise RuntimeError("Рилтайм-захват уже запущен.")
            self._state = {
                "status": "starting",
                "message": "Разрешите macOS записывать экран и использовать микрофон.",
                "system_audio": False,
                "microphone": False,
            }
            self._started_at = None
            self._process = subprocess.Popen(
                [str(helper)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            process = self._process

        threading.Thread(
            target=self._read_events, args=(process,), daemon=True
        ).start()
        threading.Thread(target=self._wait, args=(process,), daemon=True).start()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if not process or process.poll() is not None:
                self._state.update(
                    status="idle",
                    message="Захват уже остановлен.",
                )
                self._started_at = None
                already_stopped = True
            else:
                self._state.update(status="stopping", message="Останавливаем захват…")
                already_stopped = False

        if already_stopped:
            return self.snapshot()

        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        return self.snapshot()

    def _read_events(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_name = event.get("event")
            with self._lock:
                if process is not self._process:
                    return
                if event_name == "started":
                    self._state.update(
                        status="recording",
                        message="Захватываем системный звук и микрофон локально.",
                    )
                    self._started_at = time.monotonic()
                elif event_name == "audio_detected":
                    source = event.get("source")
                    if source == "system":
                        self._state["system_audio"] = True
                    elif source == "microphone":
                        self._state["microphone"] = True
                elif event_name == "error":
                    self._state.update(
                        status="error",
                        message=self._friendly_error(str(event.get("message", ""))),
                    )

    def _wait(self, process: subprocess.Popen[str]) -> None:
        return_code = process.wait()
        stderr = process.stderr.read().strip() if process.stderr else ""
        with self._lock:
            if process is not self._process:
                return
            current_status = self._state["status"]
            if current_status not in {"error"}:
                if return_code == 0 or current_status == "stopping":
                    self._state.update(
                        status="idle",
                        message="Захват остановлен. Аудио не сохранялось на диск.",
                    )
                else:
                    self._state.update(
                        status="error",
                        message=self._friendly_error(stderr),
                    )
            self._started_at = None

    @staticmethod
    def _friendly_error(details: str) -> str:
        lowered = details.lower()
        if "permission" in lowered or "denied" in lowered:
            return (
                "Нет разрешения macOS. Разрешите запись экрана и микрофон "
                "для Terminal или транскрибатора в Системных настройках."
            )
        return f"Не удалось запустить захват звука: {details or 'неизвестная ошибка'}"


capture_manager = RealtimeCaptureManager()
atexit.register(capture_manager.stop)
