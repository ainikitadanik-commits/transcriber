from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .core import MODEL_NAME, SUPPORTED_MODELS, TranscriptionError, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcribe-local",
        description="Локальная транскрибация длинных записей через GigaAM.",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="Один файл или несколько последовательных частей встречи",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Папка для TXT, JSON и DOCX (по умолчанию: output)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "mps", "cpu"),
        default="auto",
        help="auto пробует MPS и переходит на CPU при ошибке",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Размер пакета long-form ASR (по умолчанию: 2)",
    )
    parser.add_argument(
        "--speakers",
        action="store_true",
        help="Разделить текст по спикерам с помощью локальной pyannote",
    )
    parser.add_argument(
        "--speaker-count",
        type=int,
        help="Известное число участников (используется вместе с --speakers)",
    )
    parser.add_argument(
        "--no-gap-recovery",
        action="store_true",
        help="Не выполнять повторное распознавание подозрительных пропусков",
    )
    parser.add_argument(
        "--audio-enhancement",
        choices=("auto", "on", "off"),
        default="auto",
        help="Обработка тихих голосов: auto, on или off (по умолчанию: auto)",
    )
    parser.add_argument(
        "--enhance-audio",
        action="store_const",
        const="on",
        dest="audio_enhancement",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--model",
        choices=tuple(sorted(SUPPORTED_MODELS)),
        default=MODEL_NAME,
        help=f"Модель GigaAM (по умолчанию: {MODEL_NAME})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.batch_size < 1:
        print("Ошибка: --batch-size должен быть не меньше 1.", file=sys.stderr)
        return 2
    if args.speaker_count is not None and args.speaker_count < 1:
        print("Ошибка: --speaker-count должен быть не меньше 1.", file=sys.stderr)
        return 2
    if args.speaker_count is not None and not args.speakers:
        print("Ошибка: --speaker-count используется вместе с --speakers.", file=sys.stderr)
        return 2
    if not os.getenv("HF_TOKEN"):
        print(
            "Примечание: HF_TOKEN не задан. Он нужен только для первой загрузки "
            "моделей pyannote; при наличии кэша обработка останется локальной.",
            file=sys.stderr,
        )
    try:
        txt_path, json_path, docx_path, device, fallback_used = run(
            input_path=args.input,
            output_dir=args.output_dir,
            requested_device=args.device,
            batch_size=args.batch_size,
            diarization=args.speakers,
            speaker_count=args.speaker_count,
            recover_gaps=not args.no_gap_recovery,
            enhancement_mode=args.audio_enhancement,
            model_name=args.model,
        )
    except TranscriptionError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Ошибка GigaAM: {error}", file=sys.stderr)
        return 1

    fallback_note = " (CPU fallback)" if fallback_used else ""
    print(f"Готово. Устройство: {device}{fallback_note}")
    print(f"TXT:  {txt_path}")
    print(f"JSON: {json_path}")
    print(f"DOCX: {docx_path}")
    return 0
