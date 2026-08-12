from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .core import DIARIZATION_MODEL, TranscriptionError
from .models import local_snapshot, prepare_pyannote_models
from .realtime_asr import (
    PCM_SAMPLE_RATE,
    SOURCE_SYSTEM,
    RealtimeSpeakerTurn,
)


@dataclass
class _SpeakerProfile:
    name: str
    centroid: Any
    observations: int = 1


@dataclass
class _PendingSpeaker:
    centroid: Any
    observations: int
    last_seen: int


class PyannoteRealtimeDiarizer:
    """Windowed diarization with stable anonymous speaker labels."""

    def __init__(
        self,
        pipeline: Any,
        *,
        similarity_threshold: float = 0.65,
        max_profiles: int = 16,
        minimum_speech_seconds: float = 0.5,
        confirmation_observations: int = 2,
    ) -> None:
        if not 0.0 < similarity_threshold < 1.0:
            raise ValueError("Порог сходства голоса должен быть между 0 и 1.")
        if max_profiles < 1:
            raise ValueError("Максимум профилей спикеров должен быть положительным.")
        if minimum_speech_seconds <= 0:
            raise ValueError("Минимальная длительность речи должна быть положительной.")
        if confirmation_observations < 2:
            raise ValueError("Новый голос должен подтверждаться не менее двух раз.")
        self._pipeline = pipeline
        self._similarity_threshold = similarity_threshold
        self._max_profiles = max_profiles
        self._minimum_speech_seconds = minimum_speech_seconds
        self._confirmation_observations = confirmation_observations
        self._profiles: list[_SpeakerProfile] = []
        self._pending: list[_PendingSpeaker] = []
        self._observation = 0
        self._embedding_dimension: int | None = None
        self._lock = threading.Lock()

    def __call__(
        self, source: str, pcm: bytes, sample_rate: int
    ) -> tuple[RealtimeSpeakerTurn, ...]:
        if source != SOURCE_SYSTEM or not pcm:
            return ()
        if sample_rate != PCM_SAMPLE_RATE or len(pcm) % 2:
            raise ValueError("Diarization принимает PCM s16le mono 16 кГц.")

        import numpy as np
        import torch

        waveform = (
            torch.frombuffer(bytearray(pcm), dtype=torch.int16)
            .to(dtype=torch.float32)
            .div_(32_768.0)
            .unsqueeze(0)
        )
        with self._lock, torch.inference_mode():
            output = self._pipeline(
                {"waveform": waveform, "sample_rate": sample_rate}
            )
            annotation = output.exclusive_speaker_diarization
            profile_annotation = output.speaker_diarization
            profile_labels = list(profile_annotation.labels())
            self._observation += 1
            self._pending = [
                pending
                for pending in self._pending
                if self._observation - pending.last_seen <= 4
            ]
            if output.speaker_embeddings is None:
                mapping = {}
            else:
                durations = {label: 0.0 for label in profile_labels}
                for turn, _, label in profile_annotation.itertracks(yield_label=True):
                    durations[label] = durations.get(label, 0.0) + max(
                        0.0, float(turn.end) - float(turn.start)
                    )
                try:
                    embeddings = np.asarray(output.speaker_embeddings)
                    mapping = self._match_profiles(
                        profile_labels, embeddings, durations, np
                    )
                except (TypeError, ValueError):
                    mapping = {}

        return tuple(
            RealtimeSpeakerTurn(
                start=float(turn.start),
                end=float(turn.end),
                speaker=mapping.get(label, "Спикер не определён"),
            )
            for turn, _, label in annotation.itertracks(yield_label=True)
        )

    def _match_profiles(self, labels, embeddings, durations, np) -> dict[str, str]:
        if embeddings.ndim == 0 or len(labels) != len(embeddings):
            return {}
        normalized: list[Any | None] = []
        for embedding in embeddings:
            embedding = np.asarray(embedding, dtype=np.float32)
            if (
                embedding.ndim != 1
                or not np.all(np.isfinite(embedding))
                or durations.get(labels[len(normalized)], 0.0)
                < self._minimum_speech_seconds
                or (
                    self._embedding_dimension is not None
                    and embedding.size != self._embedding_dimension
                )
            ):
                normalized.append(None)
                continue
            norm = float(np.linalg.norm(embedding))
            if norm <= 1e-8:
                normalized.append(None)
                continue
            self._embedding_dimension = embedding.size
            normalized.append(embedding / norm)

        candidates: list[tuple[float, int, int]] = []
        for local_index, embedding in enumerate(normalized):
            if embedding is None:
                continue
            for profile_index, profile in enumerate(self._profiles):
                if embedding.shape != profile.centroid.shape:
                    continue
                score = float(np.dot(embedding, profile.centroid))
                if score >= self._similarity_threshold:
                    candidates.append((score, local_index, profile_index))
        candidates.sort(reverse=True)

        matched_local: set[int] = set()
        matched_profiles: set[int] = set()
        assignments: dict[int, int] = {}
        for _score, local_index, profile_index in candidates:
            if local_index in matched_local or profile_index in matched_profiles:
                continue
            assignments[local_index] = profile_index
            matched_local.add(local_index)
            matched_profiles.add(profile_index)

        pending_candidates: list[tuple[float, int, int]] = []
        for local_index, embedding in enumerate(normalized):
            if embedding is None or local_index in assignments:
                continue
            for pending_index, pending in enumerate(self._pending):
                if embedding.shape != pending.centroid.shape:
                    continue
                score = float(np.dot(embedding, pending.centroid))
                if score >= self._similarity_threshold:
                    pending_candidates.append((score, local_index, pending_index))
        pending_candidates.sort(reverse=True)

        matched_pending: set[int] = set()
        promoted_pending: set[int] = set()
        promoted_local: set[int] = set()
        for _score, local_index, pending_index in pending_candidates:
            if local_index in matched_local or pending_index in matched_pending:
                continue
            pending = self._pending[pending_index]
            total = pending.observations + 1
            centroid = (
                pending.centroid * pending.observations + normalized[local_index]
            ) / total
            norm = float(np.linalg.norm(centroid))
            pending.centroid = centroid / norm if norm > 0 else centroid
            pending.observations = total
            pending.last_seen = self._observation
            matched_local.add(local_index)
            matched_pending.add(pending_index)
            if total >= self._confirmation_observations:
                promoted_pending.add(pending_index)
                if len(self._profiles) < self._max_profiles:
                    profile_index = len(self._profiles)
                    self._profiles.append(
                        _SpeakerProfile(
                            name=f"Спикер {profile_index + 1}",
                            centroid=pending.centroid,
                            observations=total,
                        )
                    )
                    assignments[local_index] = profile_index
                    promoted_local.add(local_index)

        for local_index, embedding in enumerate(normalized):
            if embedding is None or local_index in matched_local:
                continue
            if len(self._pending) < self._max_profiles * 2:
                self._pending.append(
                    _PendingSpeaker(
                        centroid=embedding,
                        observations=1,
                        last_seen=self._observation,
                    )
                )
            matched_local.add(local_index)

        if promoted_pending:
            self._pending = [
                pending
                for index, pending in enumerate(self._pending)
                if index not in promoted_pending
            ]

        for local_index, profile_index in assignments.items():
            if local_index in promoted_local:
                continue
            profile = self._profiles[profile_index]
            total = profile.observations + 1
            centroid = (
                profile.centroid * profile.observations + normalized[local_index]
            ) / total
            norm = float(np.linalg.norm(centroid))
            profile.centroid = centroid / norm if norm > 0 else centroid
            profile.observations = total

        return {
            label: self._profiles[assignments[index]].name
            for index, label in enumerate(labels)
            if index in assignments
        }


def load_realtime_diarizer(
    device: str,
    *,
    token: str | None = None,
) -> PyannoteRealtimeDiarizer:
    prepare_pyannote_models(token, diarization=True)
    try:
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(local_snapshot(DIARIZATION_MODEL))
        pipeline.to(torch.device(device))
    except Exception as error:
        raise TranscriptionError(
            f"Не удалось загрузить локальную модель разделения спикеров: {error}"
        ) from error
    return PyannoteRealtimeDiarizer(pipeline)
