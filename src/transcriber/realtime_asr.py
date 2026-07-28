from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol


PCM_SAMPLE_RATE = 16_000
PCM_SAMPLE_WIDTH = 2
MAX_WINDOW_SECONDS = 25.0
SOURCE_SYSTEM = "system"
SOURCE_MICROPHONE = "microphone"
SOURCES = (SOURCE_SYSTEM, SOURCE_MICROPHONE)


class InMemoryASR(Protocol):
    def __call__(self, source: str, pcm: bytes, sample_rate: int) -> str: ...


class CaptureSource(Protocol):
    def drain_audio(self, source: str, max_bytes: int | None = None) -> bytes: ...


class BackpressureError(RuntimeError):
    pass


@dataclass(frozen=True)
class RealtimeSegment:
    source: str
    start: float
    end: float
    text: str
    committed: bool


@dataclass(frozen=True)
class RealtimeSnapshot:
    committed: tuple[RealtimeSegment, ...]
    provisional: dict[str, RealtimeSegment]
    buffered_seconds: dict[str, float]
    backlogged_windows: dict[str, int]
    finalized: bool


@dataclass
class _SourceState:
    pcm: bytearray = field(default_factory=bytearray)
    buffer_start_samples: int = 0
    last_window_end_samples: int = 0
    provisional: RealtimeSegment | None = None


def _token_key(token: str) -> str:
    normalized = re.sub(r"^\W+|\W+$", "", token, flags=re.UNICODE).casefold()
    return normalized or token.casefold()


def longest_token_overlap(left: list[str], right: list[str]) -> int:
    left_keys = [_token_key(token) for token in left]
    right_keys = [_token_key(token) for token in right]
    for size in range(min(len(left_keys), len(right_keys)), 0, -1):
        if left_keys[-size:] == right_keys[:size]:
            return size
    return 0


class RealtimeASRSession:
    def __init__(
        self,
        asr: InMemoryASR,
        *,
        capture: CaptureSource | None = None,
        window_seconds: float = 20.0,
        overlap_seconds: float = 2.0,
        max_buffer_seconds: float = 120.0,
        max_windows_per_pump: int = 4,
        max_pending_segments: int = 1_024,
    ) -> None:
        if not 0 < window_seconds <= MAX_WINDOW_SECONDS:
            raise ValueError("ASR-окно должно быть больше 0 и не длиннее 25 секунд.")
        if not 0 <= overlap_seconds < window_seconds:
            raise ValueError("Overlap должен быть неотрицательным и короче окна.")
        if max_buffer_seconds < window_seconds:
            raise ValueError("PCM-буфер не может быть короче ASR-окна.")
        if max_windows_per_pump < 1:
            raise ValueError("За один проход нужно обрабатывать хотя бы одно окно.")
        if max_pending_segments < 1:
            raise ValueError("Очередь committed-сегментов не может быть пустой.")

        self._asr = asr
        self._capture = capture
        self._window_samples = round(window_seconds * PCM_SAMPLE_RATE)
        self._overlap_samples = round(overlap_seconds * PCM_SAMPLE_RATE)
        self._step_samples = self._window_samples - self._overlap_samples
        self._window_bytes = self._window_samples * PCM_SAMPLE_WIDTH
        self._step_bytes = self._step_samples * PCM_SAMPLE_WIDTH
        self._max_buffer_bytes = round(
            max_buffer_seconds * PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH
        )
        self._max_windows_per_pump = max_windows_per_pump
        self._max_pending_segments = max_pending_segments
        self._sources = {source: _SourceState() for source in SOURCES}
        self._committed: deque[RealtimeSegment] = deque()
        self._next_source_index = 0
        self._finalized = False

    def push(self, source: str, pcm: bytes) -> None:
        self._require_active()
        state = self._source(source)
        if len(pcm) % PCM_SAMPLE_WIDTH:
            raise ValueError("PCM должен содержать целое число 16-битных сэмплов.")
        if len(state.pcm) + len(pcm) > self._max_buffer_bytes:
            raise BackpressureError(
                f"PCM-буфер источника {source} переполнен; сначала обработайте окна."
            )
        state.pcm.extend(pcm)

    def pull_capture(
        self,
        *,
        max_bytes_per_source: int | None = None,
        max_windows: int | None = None,
    ) -> RealtimeSnapshot:
        self._require_active()
        if self._capture is None:
            raise RuntimeError("Источник capture не передан.")
        for source in SOURCES:
            state = self._sources[source]
            capacity = self._max_buffer_bytes - len(state.pcm)
            if capacity <= 0:
                raise BackpressureError(
                    f"PCM-буфер источника {source} заполнен; capture приостановлен."
                )
            limit = (
                capacity
                if max_bytes_per_source is None
                else min(capacity, max_bytes_per_source)
            )
            pcm = self._capture.drain_audio(source, limit)
            if pcm:
                self.push(source, pcm)
        return self.process_ready(max_windows=max_windows)

    def process_ready(self, max_windows: int | None = None) -> RealtimeSnapshot:
        self._require_active()
        budget = self._max_windows_per_pump if max_windows is None else max_windows
        if budget < 1:
            raise ValueError("max_windows должен быть положительным.")
        for _ in range(budget):
            source = self._next_ready_source()
            if source is None:
                break
            self._process_full_window(source)
        return self.snapshot()

    def stop(self) -> RealtimeSnapshot:
        if self._finalized:
            return self.snapshot()

        while self._next_ready_source(peek=True) is not None:
            self.process_ready(max_windows=1)

        for source in SOURCES:
            state = self._sources[source]
            buffered_samples = len(state.pcm) // PCM_SAMPLE_WIDTH
            buffer_end = state.buffer_start_samples + buffered_samples
            if state.pcm and buffer_end > state.last_window_end_samples:
                self._ensure_commit_capacity(state)
                self._accept_result(
                    source,
                    state,
                    state.buffer_start_samples,
                    buffer_end,
                    self._asr(source, bytes(state.pcm), PCM_SAMPLE_RATE),
                )
            state.pcm.clear()
            state.buffer_start_samples = buffer_end

        provisionals = sorted(
            (
                state.provisional
                for state in self._sources.values()
                if state.provisional is not None
            ),
            key=lambda segment: (
                segment.start,
                segment.end,
                SOURCES.index(segment.source),
            ),
        )
        for segment in provisionals:
            self._append_committed(
                RealtimeSegment(
                    source=segment.source,
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    committed=True,
                )
            )
            self._sources[segment.source].provisional = None

        self._finalized = True
        return self.snapshot()

    def drain_committed(self) -> tuple[RealtimeSegment, ...]:
        committed = self._sorted_committed()
        self._committed.clear()
        return committed

    def snapshot(self) -> RealtimeSnapshot:
        provisional = {
            source: state.provisional
            for source, state in self._sources.items()
            if state.provisional is not None
        }
        buffered_seconds = {
            source: len(state.pcm) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH)
            for source, state in self._sources.items()
        }
        backlogged_windows = {
            source: self._ready_window_count(state)
            for source, state in self._sources.items()
        }
        return RealtimeSnapshot(
            committed=self._sorted_committed(),
            provisional=provisional,
            buffered_seconds=buffered_seconds,
            backlogged_windows=backlogged_windows,
            finalized=self._finalized,
        )

    def _process_full_window(self, source: str) -> None:
        state = self._sources[source]
        self._ensure_commit_capacity(state)
        start = state.buffer_start_samples
        end = start + self._window_samples
        text = self._asr(
            source,
            bytes(state.pcm[: self._window_bytes]),
            PCM_SAMPLE_RATE,
        )
        self._accept_result(source, state, start, end, text)
        del state.pcm[: self._step_bytes]
        state.buffer_start_samples += self._step_samples

    def _accept_result(
        self,
        source: str,
        state: _SourceState,
        start_samples: int,
        end_samples: int,
        text: str,
    ) -> None:
        tokens = text.split()
        previous = state.provisional
        if previous is not None:
            previous_tokens = previous.text.split()
            overlap = longest_token_overlap(previous_tokens, tokens)
            stable_tokens = previous_tokens[:-overlap] if overlap else previous_tokens
            if stable_tokens:
                self._append_committed(
                    RealtimeSegment(
                        source=source,
                        start=previous.start,
                        end=start_samples / PCM_SAMPLE_RATE,
                        text=" ".join(stable_tokens),
                        committed=True,
                    )
                )

        state.provisional = (
            RealtimeSegment(
                source=source,
                start=start_samples / PCM_SAMPLE_RATE,
                end=end_samples / PCM_SAMPLE_RATE,
                text=" ".join(tokens),
                committed=False,
            )
            if tokens
            else None
        )
        state.last_window_end_samples = end_samples

    def _next_ready_source(self, *, peek: bool = False) -> str | None:
        for offset in range(len(SOURCES)):
            index = (self._next_source_index + offset) % len(SOURCES)
            source = SOURCES[index]
            if len(self._sources[source].pcm) >= self._window_bytes:
                if not peek:
                    self._next_source_index = (index + 1) % len(SOURCES)
                return source
        return None

    def _ready_window_count(self, state: _SourceState) -> int:
        samples = len(state.pcm) // PCM_SAMPLE_WIDTH
        if samples < self._window_samples:
            return 0
        return 1 + (samples - self._window_samples) // self._step_samples

    def _ensure_commit_capacity(self, state: _SourceState) -> None:
        if (
            state.provisional is not None
            and len(self._committed) >= self._max_pending_segments
        ):
            raise BackpressureError(
                "Очередь committed-сегментов заполнена; сначала заберите результат."
            )

    def _append_committed(self, segment: RealtimeSegment) -> None:
        if len(self._committed) >= self._max_pending_segments:
            raise BackpressureError(
                "Очередь committed-сегментов заполнена; сначала заберите результат."
            )
        self._committed.append(segment)

    def _sorted_committed(self) -> tuple[RealtimeSegment, ...]:
        return tuple(
            sorted(
                self._committed,
                key=lambda segment: (
                    segment.start,
                    segment.end,
                    SOURCES.index(segment.source),
                ),
            )
        )

    def _source(self, source: str) -> _SourceState:
        try:
            return self._sources[source]
        except KeyError as error:
            raise ValueError(f"Неизвестный источник PCM: {source}") from error

    def _require_active(self) -> None:
        if self._finalized:
            raise RuntimeError("Realtime ASR-сессия уже завершена.")
