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


class PyannoteRealtimeDiarizer:
    """Windowed diarization with stable anonymous speaker labels."""

    def __init__(self, pipeline: Any, *, similarity_threshold: float = 0.65) -> None:
        if not 0.0 < similarity_threshold < 1.0:
            raise ValueError("Порог сходства голоса должен быть между 0 и 1.")
        self._pipeline = pipeline
        self._similarity_threshold = similarity_threshold
        self._profiles: list[_SpeakerProfile] = []
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
            embeddings = np.asarray(output.speaker_embeddings)
            local_labels = list(annotation.labels())
            mapping = self._match_profiles(local_labels, embeddings, np)

        return tuple(
            RealtimeSpeakerTurn(
                start=float(turn.start),
                end=float(turn.end),
                speaker=mapping[label],
            )
            for turn, _, label in annotation.itertracks(yield_label=True)
        )

    def _match_profiles(self, labels, embeddings, np) -> dict[str, str]:
        if len(labels) != len(embeddings):
            raise RuntimeError("pyannote вернул несогласованные голоса и embeddings.")
        normalized = []
        for embedding in embeddings:
            norm = float(np.linalg.norm(embedding))
            normalized.append(embedding / norm if norm > 0 else embedding)

        candidates: list[tuple[float, int, int]] = []
        for local_index, embedding in enumerate(normalized):
            for profile_index, profile in enumerate(self._profiles):
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

        for local_index, embedding in enumerate(normalized):
            if local_index not in assignments:
                profile_index = len(self._profiles)
                self._profiles.append(
                    _SpeakerProfile(
                        name=f"Спикер {profile_index + 1}",
                        centroid=embedding,
                    )
                )
                assignments[local_index] = profile_index
                continue
            profile = self._profiles[assignments[local_index]]
            total = profile.observations + 1
            centroid = (profile.centroid * profile.observations + embedding) / total
            norm = float(np.linalg.norm(centroid))
            profile.centroid = centroid / norm if norm > 0 else centroid
            profile.observations = total

        return {
            label: self._profiles[assignments[index]].name
            for index, label in enumerate(labels)
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
