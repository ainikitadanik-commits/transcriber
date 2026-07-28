from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .core import Segment, build_txt, choose_device, write_outputs
from .gigaam_realtime import load_realtime_adapter
from .realtime import RealtimeCaptureManager
from .realtime_asr import (
    SOURCE_MICROPHONE,
    SOURCE_SYSTEM,
    RealtimeASRSession,
    RealtimeSegment,
)


AdapterLoader = Callable[[], tuple[Callable[[str, bytes, int], str], str]]


def _default_adapter_loader():
    device = choose_device("auto")
    return load_realtime_adapter(device), device


class RealtimeTranscriptionService:
    def __init__(
        self,
        capture: RealtimeCaptureManager,
        output_dir: Path,
        *,
        adapter_loader: AdapterLoader = _default_adapter_loader,
        window_seconds: float = 12.0,
        overlap_seconds: float = 2.0,
        poll_interval: float = 0.25,
    ) -> None:
        self._capture = capture
        self._output_dir = output_dir
        self._adapter_loader = adapter_loader
        self._window_seconds = window_seconds
        self._overlap_seconds = overlap_seconds
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session: RealtimeASRSession | None = None
        self._segments: list[RealtimeSegment] = []
        self._provisional: dict[str, RealtimeSegment] = {}
        self._state: dict[str, Any] = {
            "asr_status": "idle",
            "asr_message": "Готово к запуску.",
            "device": None,
            "started_at": None,
            "completed_at": None,
            "txt_name": None,
            "json_name": None,
            "docx_name": None,
            "error": None,
        }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Realtime-транскрибация уже запущена.")
            self._segments = []
            self._provisional = {}
            self._session = None
            self._stop_event.clear()
            self._state = {
                "asr_status": "loading",
                "asr_message": "Загружаем локальную модель распознавания…",
                "device": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "txt_name": None,
                "json_name": None,
                "docx_name": None,
                "error": None,
            }

        try:
            self._capture.start()
        except Exception:
            with self._lock:
                self._state.update(
                    asr_status="error",
                    asr_message="Не удалось запустить захват звука.",
                )
            raise

        thread = threading.Thread(target=self._run, daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                already_stopped = True
            else:
                already_stopped = False
                self._state.update(
                    asr_status="finalizing",
                    asr_message="Завершаем распознавание оставшегося звука…",
                )
        if already_stopped:
            return self.snapshot()
        self._capture.stop()
        self._stop_event.set()
        return self.snapshot()

    def wait(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            committed = list(self._segments)
            provisional = dict(self._provisional)
        capture = self._capture.snapshot()
        state.update(capture)
        state["capture"] = capture
        state["segments"] = [
            self._segment_payload(segment) for segment in committed
        ]
        state["provisional"] = {
            source: self._segment_payload(segment)
            for source, segment in provisional.items()
        }
        return state

    def _run(self) -> None:
        try:
            adapter, device = self._adapter_loader()
            session = RealtimeASRSession(
                adapter,
                capture=self._capture,
                window_seconds=self._window_seconds,
                overlap_seconds=self._overlap_seconds,
            )
            with self._lock:
                self._session = session
                self._state.update(
                    asr_status="waiting_audio",
                    asr_message="Ожидаем системный звук и микрофон…",
                    device=device,
                )

            while not self._stop_event.is_set():
                capture_state = self._capture.snapshot()
                if capture_state["status"] == "error":
                    raise RuntimeError(capture_state["message"])
                if capture_state["status"] == "recording":
                    snapshot = session.pull_capture(max_windows=1)
                    self._consume(snapshot)
                    with self._lock:
                        self._state.update(
                            asr_status="running",
                            asr_message="Распознаём встречу локально…",
                        )
                self._stop_event.wait(self._poll_interval)

            for source in (SOURCE_SYSTEM, SOURCE_MICROPHONE):
                while pcm := self._capture.drain_audio(source):
                    session.push(source, pcm)
            self._consume(session.stop())
            self._export(device)
        except Exception as error:
            try:
                self._capture.stop()
            except Exception:
                pass
            with self._lock:
                self._state.update(
                    asr_status="error",
                    asr_message=f"Realtime-распознавание остановлено: {error}",
                    error={
                        "code": "realtime_asr_failed",
                        "details": str(error),
                    },
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )

    def _consume(self, snapshot) -> None:
        committed = list(snapshot.committed)
        if self._session is not None:
            self._session.drain_committed()
        with self._lock:
            self._segments.extend(committed)
            self._provisional = dict(snapshot.provisional)

    def _export(self, device: str) -> None:
        with self._lock:
            segments = list(self._segments)
            started_at = self._state["started_at"]
        core_segments = [
            Segment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=(
                    "Системный звук"
                    if segment.source == SOURCE_SYSTEM
                    else "Микрофон"
                ),
            )
            for segment in segments
            if segment.text
        ]
        completed_at = datetime.now(timezone.utc)
        document = {
            "schema_version": "1.3",
            "input": {
                "path": None,
                "name": "Realtime-встреча",
                "format": "realtime_pcm",
                "size_bytes": 0,
                "parts": [],
            },
            "processing": {
                "model": "v3_e2e_rnnt",
                "mode": "realtime",
                "device_requested": "auto",
                "device_used": device,
                "cpu_fallback_used": False,
                "batch_size": 1,
                "audio": {
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                    "codec": "pcm_s16le",
                    "enhancement_mode": "off",
                    "enhancement_applied": False,
                },
                "diarization": {
                    "enabled": False,
                    "model": None,
                    "device_used": None,
                    "num_speakers_requested": None,
                    "num_speakers": None,
                },
                "gap_recovery": {
                    "enabled": False,
                    "device_used": None,
                    "recovered_segments": 0,
                },
                "started_at": started_at,
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": round(
                    max((segment.end for segment in core_segments), default=0.0),
                    3,
                ),
            },
            "text": " ".join(segment.text for segment in core_segments),
            "segments": [
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "speaker": segment.speaker,
                    "text": segment.text,
                }
                for segment in core_segments
            ],
        }
        stem = completed_at.strftime("realtime-%Y%m%d-%H%M%S")
        txt, json_path, docx = write_outputs(
            self._output_dir,
            stem,
            build_txt(core_segments),
            document,
        )
        with self._lock:
            self._provisional = {}
            self._state.update(
                asr_status="done",
                asr_message="Realtime-транскрипция сохранена.",
                completed_at=completed_at.isoformat(),
                txt_name=txt.name,
                json_name=json_path.name,
                docx_name=docx.name,
            )

    @staticmethod
    def _segment_payload(segment: RealtimeSegment) -> dict[str, Any]:
        return {
            "source": segment.source,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text,
            "committed": segment.committed,
        }
