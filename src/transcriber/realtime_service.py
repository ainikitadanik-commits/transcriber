from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .core import Segment, build_txt, choose_device, write_outputs
from .gigaam_realtime import load_realtime_adapter
from .realtime import RealtimeCaptureManager
from .realtime_diarization import load_realtime_diarizer
from .realtime_journal import RealtimeSessionJournal, find_recoverable_sessions
from .realtime_asr import (
    SOURCE_MICROPHONE,
    SOURCE_SYSTEM,
    RealtimeASRSession,
    RealtimeSegment,
)


AdapterLoader = Callable[[], tuple[Callable, str]]
DiarizerLoader = Callable[[str, str | None], Callable]


def _default_adapter_loader():
    device = choose_device("auto")
    return load_realtime_adapter(device), device


def _default_diarizer_loader(device: str, token: str | None):
    return load_realtime_diarizer(device, token=token)


class RealtimeTranscriptionService:
    def __init__(
        self,
        capture: RealtimeCaptureManager,
        output_dir: Path,
        *,
        adapter_loader: AdapterLoader = _default_adapter_loader,
        diarizer_loader: DiarizerLoader = _default_diarizer_loader,
        window_seconds: float = 12.0,
        overlap_seconds: float = 2.0,
        poll_interval: float = 0.25,
        sessions_dir: Path | None = None,
    ) -> None:
        self._capture = capture
        self._output_dir = output_dir
        self._adapter_loader = adapter_loader
        self._diarizer_loader = diarizer_loader
        self._window_seconds = window_seconds
        self._overlap_seconds = overlap_seconds
        self._poll_interval = poll_interval
        self._sessions_dir = sessions_dir or output_dir.parent / "sessions"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_id: str | None = None
        self._journal: RealtimeSessionJournal | None = None
        self._stop_requested = False
        self._include_microphone = False
        self._diarization = False
        self._hf_token: str | None = None
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
            "microphone_enabled": False,
            "diarization_enabled": False,
            "diarization_warning": None,
            "session_id": None,
        }

    def start(
        self,
        *,
        include_microphone: bool = False,
        diarization: bool = False,
        hf_token: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Realtime-транскрибация уже запущена.")
            self._segments = []
            self._provisional = {}
            self._session = None
            self._session_id = uuid.uuid4().hex
            self._journal = RealtimeSessionJournal(
                self._sessions_dir, self._session_id
            )
            self._stop_requested = False
            self._include_microphone = include_microphone
            self._diarization = diarization
            self._hf_token = hf_token
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
                "microphone_enabled": include_microphone,
                "diarization_enabled": diarization,
                "diarization_warning": None,
                "session_id": self._session_id,
            }
            self._journal.create(
                {
                    "schema_version": 1,
                    "session_id": self._session_id,
                    "started_at": self._state["started_at"],
                    "completed_at": None,
                    "microphone_enabled": include_microphone,
                    "diarization_enabled": diarization,
                    "device": None,
                }
            )

        try:
            self._capture.start(include_microphone=include_microphone)
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
            session_id = self._session_id
            should_stop_capture = bool(
                thread and thread.is_alive() and not self._stop_requested
            )
            if should_stop_capture:
                self._stop_requested = True
                self._state.update(
                    asr_status="finalizing",
                    asr_message="Завершаем распознавание оставшегося звука…",
                )
        if should_stop_capture:
            threading.Thread(
                target=self._stop_capture_and_signal,
                daemon=True,
            ).start()
        return {"session_id": session_id, "status": "finalizing"}

    def _stop_capture_and_signal(self) -> None:
        try:
            self._capture.stop()
        finally:
            self._stop_event.set()

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
            segment_count = len(self._segments)
            provisional_count = len(self._provisional)
        capture = self._capture.snapshot()
        state.update(capture)
        state["capture"] = capture
        state["segment_count"] = segment_count
        state["next_cursor"] = segment_count
        state["provisional_count"] = provisional_count
        return state

    def segments(self, *, after: int = 0, limit: int = 200) -> dict[str, Any]:
        if after < 0 or limit < 1:
            raise ValueError("Cursor and limit must be positive.")
        with self._lock:
            total = len(self._segments)
            end = min(after + limit, total)
            selected = list(self._segments[after:end]) if after < total else []
        return {
            "segments": [self._segment_payload(segment) for segment in selected],
            "next_cursor": end if after < total else total,
            "has_more": end < total,
        }

    def recoverable_sessions(self) -> list[dict[str, Any]]:
        return find_recoverable_sessions(self._sessions_dir)

    def recover(self, session_id: str) -> dict[str, Any]:
        if (
            Path(session_id).name != session_id
            or session_id in {".", ".."}
            or "/" in session_id
        ):
            raise ValueError("Некорректный session_id.")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Сначала завершите текущую realtime-сессию.")
        journal = RealtimeSessionJournal(self._sessions_dir, session_id)
        metadata = journal.metadata()
        payloads = journal.load_segments()
        if metadata.get("completed_at"):
            raise RuntimeError("Сессия уже завершена.")
        segments = [RealtimeSegment(**payload) for payload in payloads]
        with self._lock:
            self._session_id = session_id
            self._journal = journal
            self._segments = segments
            self._provisional = {}
            self._diarization = bool(metadata.get("diarization_enabled"))
            self._include_microphone = bool(metadata.get("microphone_enabled"))
            self._state.update(
                session_id=session_id,
                started_at=metadata.get("started_at"),
                asr_status="finalizing",
                asr_message="Восстанавливаем сохранённую транскрипцию…",
                error=None,
            )
        self._export(metadata.get("device") or "unknown")
        return self.snapshot()

    def _run(self) -> None:
        try:
            adapter, device = self._adapter_loader()
            hf_token = self._hf_token
            self._hf_token = None
            diarizer = (
                self._diarizer_loader(device, hf_token)
                if self._diarization
                else None
            )
            session = RealtimeASRSession(
                adapter,
                diarizer=diarizer,
                capture=self._capture,
                window_seconds=self._window_seconds,
                overlap_seconds=self._overlap_seconds,
                sources=(
                    (SOURCE_SYSTEM, SOURCE_MICROPHONE)
                    if self._include_microphone
                    else (SOURCE_SYSTEM,)
                ),
            )
            with self._lock:
                self._session = session
                self._state.update(
                    asr_status="waiting_audio",
                    asr_message=(
                        "Ожидаем системный звук и микрофон…"
                        if self._include_microphone
                        else "Ожидаем системный звук…"
                    ),
                    device=device,
                )
                journal = self._journal
            if journal is not None:
                journal.update_metadata({"device": device})

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

            sources = (
                (SOURCE_SYSTEM, SOURCE_MICROPHONE)
                if self._include_microphone
                else (SOURCE_SYSTEM,)
            )
            for source in sources:
                while pcm := self._capture.drain_audio(source):
                    session.push(source, pcm)
            self._consume(session.stop())
            self._export(device)
        except Exception as error:
            self._hf_token = None
            if not self._stop_requested:
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
        journal = self._journal
        if journal is not None:
            journal.append(self._segment_payload(segment) for segment in committed)
        with self._lock:
            self._segments.extend(committed)
            self._provisional = dict(snapshot.provisional)
            self._state["diarization_warning"] = snapshot.diarization_warning

    def _export(self, device: str) -> None:
        with self._lock:
            segments = list(self._segments)
            started_at = self._state["started_at"]
            journal = self._journal
        core_segments = [
            Segment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=segment.speaker or (
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
                    "enabled": self._diarization,
                    "model": (
                        "pyannote/speaker-diarization-community-1"
                        if self._diarization
                        else None
                    ),
                    "device_used": device if self._diarization else None,
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
        if journal is not None:
            journal.update_metadata(
                {
                    "completed_at": completed_at.isoformat(),
                    "txt_name": txt.name,
                    "json_name": json_path.name,
                    "docx_name": docx.name,
                }
            )

    @staticmethod
    def _segment_payload(segment: RealtimeSegment) -> dict[str, Any]:
        return {
            "source": segment.source,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text,
            "committed": segment.committed,
            "speaker": segment.speaker,
        }
