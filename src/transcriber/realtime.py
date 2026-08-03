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


PCM_SAMPLE_RATE = 16_000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2
PCM_BUFFER_SECONDS = 120
PCM_BUFFER_LIMIT = (
    PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH * PCM_BUFFER_SECONDS
)
PERMISSION_STATES = {
    "disabled",
    "unknown",
    "requesting",
    "granted",
    "denied",
    "managed_denied",
    "unavailable",
}


class PCMBuffer:
    def __init__(self, limit: int = PCM_BUFFER_LIMIT) -> None:
        self._limit = limit
        self._data = bytearray()
        self.total_bytes = 0

    def append(self, data: bytes) -> None:
        self._data.extend(data)
        self.total_bytes += len(data)
        overflow = len(self._data) - self._limit
        if overflow > 0:
            del self._data[:overflow]

    def drain(self, max_bytes: int | None = None) -> bytes:
        count = len(self._data) if max_bytes is None else min(max_bytes, len(self._data))
        data = bytes(self._data[:count])
        del self._data[:count]
        return data

    @property
    def buffered_bytes(self) -> int:
        return len(self._data)


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
            "microphone_enabled": False,
            "permissions": {
                "system": "unknown",
                "microphone": "unknown",
            },
            "error": None,
        }
        self._started_at: float | None = None
        self._audio = {
            "system": PCMBuffer(),
            "microphone": PCMBuffer(),
        }

    def snapshot(self) -> dict[str, Any]:
        helper = capture_helper_path()
        with self._lock:
            state = dict(self._state)
            started_at = self._started_at
            state["audio_format"] = {
                "sample_rate": PCM_SAMPLE_RATE,
                "channels": PCM_CHANNELS,
                "sample_width": PCM_SAMPLE_WIDTH,
                "encoding": "pcm_s16le",
            }
            state["system_buffered_seconds"] = round(
                self._audio["system"].buffered_bytes
                / (PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH),
                2,
            )
            state["microphone_buffered_seconds"] = round(
                self._audio["microphone"].buffered_bytes
                / (PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH),
                2,
            )
        state["available"] = helper.is_file() and os.access(helper, os.X_OK)
        state["elapsed_seconds"] = (
            max(0, int(time.monotonic() - started_at)) if started_at else 0
        )
        return state

    def start(self, *, include_microphone: bool = False) -> dict[str, Any]:
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
                "message": (
                    "Подтвердите доступ к системному звуку и микрофону."
                    if include_microphone
                    else "Подтвердите доступ к системному звуку."
                ),
                "system_audio": False,
                "microphone": False,
                "microphone_enabled": include_microphone,
                "permissions": {
                    "system": "requesting",
                    "microphone": "requesting" if include_microphone else "disabled",
                },
                "error": None,
            }
            self._started_at = None
            self._audio = {
                "system": PCMBuffer(),
                "microphone": PCMBuffer(),
            }
            system_read, system_write = os.pipe()
            microphone_read = microphone_write = None
            command = [str(helper), "--system-fd", str(system_write)]
            pass_fds = [system_write]
            if include_microphone:
                microphone_read, microphone_write = os.pipe()
                command.extend(["--microphone-fd", str(microphone_write)])
                pass_fds.append(microphone_write)
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    pass_fds=tuple(pass_fds),
                )
            except OSError as error:
                os.close(system_read)
                if microphone_read is not None:
                    os.close(microphone_read)
                self._state.update(
                    status="error",
                    message=f"Не удалось запустить локальный помощник: {error}",
                )
                raise RuntimeError(self._state["message"]) from error
            finally:
                os.close(system_write)
                if microphone_write is not None:
                    os.close(microphone_write)
            process = self._process

        threading.Thread(
            target=self._read_pcm,
            args=(process, "system", system_read),
            daemon=True,
        ).start()
        if microphone_read is not None:
            threading.Thread(
                target=self._read_pcm,
                args=(process, "microphone", microphone_read),
                daemon=True,
            ).start()
        threading.Thread(
            target=self._read_events, args=(process,), daemon=True
        ).start()
        threading.Thread(target=self._wait, args=(process,), daemon=True).start()
        return self.snapshot()

    def drain_audio(self, source: str, max_bytes: int | None = None) -> bytes:
        if source not in self._audio:
            raise ValueError(f"Неизвестный источник звука: {source}")
        with self._lock:
            return self._audio[source].drain(max_bytes)

    def _read_pcm(
        self,
        process: subprocess.Popen[str],
        source: str,
        file_descriptor: int,
    ) -> None:
        with os.fdopen(file_descriptor, "rb", buffering=0) as stream:
            while data := stream.read(32 * 1024):
                with self._lock:
                    if process is not self._process:
                        return
                    self._audio[source].append(data)
                    self._state[f"{source}_audio"] = True

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
                    microphone_enabled = bool(
                        self._state.get("microphone_enabled", False)
                    )
                    self._state.update(
                        status="recording",
                        message=(
                            "Захватываем системный звук и микрофон локально."
                            if microphone_enabled
                            else "Захватываем только системный звук локально."
                        ),
                    )
                    permissions = dict(self._state["permissions"])
                    for source in ("system", "microphone"):
                        if permissions[source] == "requesting":
                            permissions[source] = "granted"
                    self._state["permissions"] = permissions
                    self._started_at = time.monotonic()
                elif event_name == "permission_state":
                    source = event.get("source")
                    permission_state = event.get("state")
                    if (
                        source in {"system", "microphone"}
                        and permission_state in PERMISSION_STATES
                    ):
                        permissions = dict(self._state["permissions"])
                        permissions[source] = permission_state
                        self._state["permissions"] = permissions
                elif event_name == "audio_detected":
                    source = event.get("source")
                    if source == "system":
                        self._state["system_audio"] = True
                    elif source == "microphone":
                        self._state["microphone"] = True
                elif event_name == "error":
                    error = self._structured_error(event)
                    source = error.get("source")
                    if source in {"system", "microphone"}:
                        state_by_code = {
                            "permission_denied": "denied",
                            "permission_restricted": "denied",
                            "permission_managed_denied": "managed_denied",
                            "device_unavailable": "unavailable",
                        }
                        permission_state = state_by_code.get(error["code"])
                        if permission_state:
                            permissions = dict(self._state["permissions"])
                            permissions[source] = permission_state
                            self._state["permissions"] = permissions
                    self._state.update(
                        status="error",
                        message=self._error_message(error),
                        error=error,
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
                    error = {
                        "code": "capture_process_failed",
                        "domain": "runtime",
                        "native_code": return_code,
                        "source": None,
                        "retryable": True,
                        "details": stderr,
                    }
                    self._state.update(
                        status="error",
                        message=self._error_message(error),
                        error=error,
                    )
            self._started_at = None

    @staticmethod
    def _structured_error(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": str(event.get("error_code") or "capture_failed"),
            "domain": str(event.get("error_domain") or "capture"),
            "native_code": event.get("native_code"),
            "source": event.get("source"),
            "retryable": bool(event.get("retryable", False)),
            "details": str(event.get("message") or ""),
        }

    @staticmethod
    def _error_message(error: dict[str, Any]) -> str:
        code = error["code"]
        source = error.get("source")
        if code in {"permission_denied", "permission_restricted"}:
            target = (
                "к системному звуку"
                if source == "system"
                else "к микрофону"
                if source == "microphone"
                else "к звуку"
            )
            return (
                f"macOS не предоставила доступ {target}. "
                "Повторите запуск и подтвердите системный запрос."
            )
        if code == "permission_managed_denied":
            return (
                "Доступ к звуку запрещён политикой устройства. "
                "Приложение не может обойти это ограничение."
            )
        if code == "device_unavailable":
            return "Источник звука недоступен. Проверьте выбранное аудиоустройство."
        details = error.get("details") or "неизвестная ошибка"
        return f"Не удалось запустить захват звука: {details}"

    @staticmethod
    def _friendly_error(details: str) -> str:
        lowered = details.lower()
        if (
            "permission" in lowered
            or "denied" in lowered
            or "userdeclined" in lowered
        ):
            return (
                "Нет разрешения macOS на системный звук или микрофон. "
                "Проверьте доступ Транскрибатора в Системных настройках."
            )
        return RealtimeCaptureManager._error_message(
            {
                "code": "capture_failed",
                "source": None,
                "details": details,
            }
        )


capture_manager = RealtimeCaptureManager()
atexit.register(capture_manager.stop)
