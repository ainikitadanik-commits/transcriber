from __future__ import annotations

import threading
from typing import Any

from .core import MODEL_NAME, load_model
from .realtime_asr import (
    MAX_WINDOW_SECONDS,
    PCM_SAMPLE_RATE,
    RealtimeASRResult,
    RealtimeWord,
)


class GigaAMInMemoryAdapter:
    def __init__(self, model: Any) -> None:
        self._model = model
        self._lock = threading.Lock()
        for attribute in ("_device", "_dtype", "_decode", "forward"):
            if not hasattr(model, attribute):
                raise TypeError(
                    f"Закреплённая GigaAM-модель не поддерживает {attribute}."
                )

    def __call__(self, source: str, pcm: bytes, sample_rate: int) -> RealtimeASRResult:
        del source
        if sample_rate != PCM_SAMPLE_RATE:
            raise ValueError("GigaAM realtime принимает только PCM 16 кГц.")
        if len(pcm) % 2:
            raise ValueError("PCM должен содержать целое число int16-сэмплов.")
        sample_count = len(pcm) // 2
        if sample_count > MAX_WINDOW_SECONDS * sample_rate:
            raise ValueError("Realtime-окно превышает лимит GigaAM 25 секунд.")
        if not pcm:
            return RealtimeASRResult("")

        import torch

        waveform = (
            torch.frombuffer(bytearray(pcm), dtype=torch.int16)
            .to(dtype=torch.float32)
            .div_(32_768.0)
            .to(self._model._device)
            .to(self._model._dtype)
            .unsqueeze(0)
        )
        length = torch.full(
            [1],
            waveform.shape[-1],
            device=self._model._device,
        )
        with self._lock, torch.inference_mode():
            encoded, encoded_length = self._model.forward(waveform, length)
            text, words = self._model._decode(
                encoded,
                encoded_length,
                length,
                True,
            )[0]
        return RealtimeASRResult(
            text=str(text).strip(),
            words=tuple(
                RealtimeWord(
                    start=float(word.start),
                    end=float(word.end),
                    text=str(word.text).strip(),
                )
                for word in (words or [])
                if str(word.text).strip()
            ),
        )


def load_realtime_adapter(
    device: str,
    model_name: str = MODEL_NAME,
) -> GigaAMInMemoryAdapter:
    return GigaAMInMemoryAdapter(load_model(device, model_name))
