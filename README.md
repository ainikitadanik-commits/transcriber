# Транскрибатор

Локальный транскрибатор рабочих встреч на базе официального
[GigaAM](https://github.com/salute-developers/GigaAM). Модель
`v3_e2e_rnnt` используется по умолчанию; для сравнения доступна
`v3_e2e_ctc`. Обе добавляют пунктуацию и нормализуют текст.

Записи и результаты обрабатываются на Mac пользователя и не отправляются во
внешние сервисы. Базовая файловая и realtime-транскрибация использует
встроенные модели GigaAM и не требует сети. Интернет нужен только для
опциональной загрузки моделей pyannote при включении разделения по спикерам.
Подробнее: [локальная обработка и приватность](docs/PRIVACY.md).

## Скачать готовую версию для Mac

Внешний DMG версии 0.2.0 пока не опубликован: на машине сборки отсутствуют
Developer ID identity и Apple notary profile. Старый ad-hoc DMG 0.1.1 является
архивным и не предназначен для передачи коллегам.

Готовым считается только файл `Transcriber-0.2.0-macOS-arm64.dmg`, рядом с
которым находятся `.sha256` и `.manifest.txt`. Он должен быть подписан
Developer ID, нотариализован, stapled и проверен Gatekeeper. Установка
выполняется в `~/Applications` без admin-прав по инструкции внутри DMG.

### Первый запуск

Только для опционального разделения по спикерам пользователь:

1. принимает условия
   [`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0);
2. для разделения по спикерам также принимает условия
   [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1);
3. создаёт личный Hugging Face token с правом `Read`;
4. один раз вставляет token в скрытое поле интерфейса.

Token используется только для загрузки моделей, не записывается приложением на
диск и удаляется из процесса до начала транскрибации. После загрузки моделей
приложение переключает Hugging Face в офлайн-режим.

### Где находятся файлы

Все рабочие данные расположены только в:

```text
~/Library/Application Support/Транскрибатор
```

- `input` — загруженные записи;
- `output` — TXT, DOCX и JSON;
- `models` — локальный кэш моделей;
- `logs` — локальные журналы работы.

Удаление этой папки удалит модели, записи, результаты и само пользовательское
окружение транскрибатора. Файл запуска находится в
`~/Applications/Транскрибатор`.

## Возможности MVP

- вход: `.webm`, `.mp4`, `.mp3`, `.m4a` и другие распространённые аудиоформаты;
- обработка: полностью локально после первоначальной загрузки моделей;
- выход: читаемые `TXT`, `DOCX` и структурированный `JSON`;
- несколько последовательных файлов можно объединить в одну встречу со сквозными таймкодами;
- опциональное локальное разделение текста по спикерам;
- повторное распознавание длинных пропусков VAD включено по умолчанию;
- опциональное выравнивание громкости тихих голосов;
- без субтитров и без распознавания имён участников.

## Требования для запуска из исходников

- macOS arm64;
- Python 3.11 или 3.12 в отдельном окружении;
- FFmpeg в `PATH`;
- для первой long-form загрузки: принятые условия
  [`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0)
  и Hugging Face token с правом чтения.
- для разделения по спикерам: также принятые условия
  [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1).

Системный Python 3.14 для этого проекта не используется.

## Запуск из исходников

Клонируйте репозиторий:

```bash
git clone https://github.com/ainikitadanik-commits/transcriber.git
cd transcriber
```

Установите зависимости в отдельное окружение:

```bash
brew install python@3.12 ffmpeg
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Пакет берётся из официального GitHub-репозитория GigaAM и закреплён на
проверенном commit `559d88d6b72541412743929f633a6ae7c9950b85`. При первом запуске
дополнительно загружаются веса GigaAM и VAD-модель pyannote.

## Использование

### Веб-интерфейс

Дважды нажмите на `Запустить транскрибатор.command` в Finder. Откроется локальная
страница, где можно:

- перетащить или выбрать запись;
- выбрать `Автоматически`, MPS или CPU;
- выбрать RNNT или CTC;
- включить восстановление пропусков;
- выбрать обработку тихих голосов: `Авто`, `Вкл` или `Выкл`;
- кнопкой `＋` добавить вторую и последующие части встречи в правильном порядке;
- следить за этапом обработки и ориентировочным прогрессом в процентах;
- при необходимости включить «Разделить по спикерам»;
- указать известное число участников для более устойчивого разделения;
- один раз ввести Hugging Face token в скрытое поле;
- скачать готовые TXT, DOCX и JSON;
- открыть в Finder папки записей и транскрипций для ручной очистки.

Процент строится по фактически завершённым этапам и плавно продвигается во время
работы модели. GigaAM не сообщает точный прогресс внутри вычислительного пакета,
поэтому шкала является ориентировочной и показывает `100%` только после создания
всех выходных файлов.

Интерфейс доступен только на этом Mac по адресу `http://127.0.0.1:7860`. Загруженные
файлы сохраняются в `input`, результаты — в `output`. Чтобы остановить его, закройте
окно Terminal.

Запуск из Terminal:

```bash
source .venv/bin/activate
scripts/build_realtime_helper.sh
transcribe-ui
```

Сборка Swift-помощника нужна только для режима «Рилтайм». При первом запуске
macOS попросит разрешить запись экрана/системного звука и доступ к микрофону.
Помощник преобразует оба потока в mono PCM 16 кГц и передаёт их основному
процессу только через локальные pipe-каналы. Исходный поток не записывается на
диск. Потоковое распознавание накопленных аудиочанков GigaAM остаётся отдельным
этапом; текущая realtime-приёмка подтверждает захват и буферизацию звука.

### Командная строка

Не пишите токен в `.env`, команду или чат. Введите его скрыто только в
текущую сессию Terminal:

```bash
read -s "HF_TOKEN?Hugging Face token: "
export HF_TOKEN
echo
transcribe-local input/meeting.webm --output-dir output
unset HF_TOKEN
```

После того как необходимые модели попали в локальный кэш, `HF_TOKEN` не нужен и
повторная обработка идет без сети.

Обычный запуск:

```bash
source .venv/bin/activate
transcribe-local input/meeting.mp4 --output-dir output
```

Аудиофайлы обрабатываются той же командой:

```bash
transcribe-local input/meeting.mp3 --output-dir output
transcribe-local input/meeting.m4a --output-dir output
```

Несколько последовательных частей передаются в нужном порядке. Они сначала
объединяются в одну встречу, поэтому таймкоды второй части продолжаются после
окончания первой:

```bash
transcribe-local input/meeting-1.m4a input/meeting-2.m4a input/meeting-3.mp3 \
  --output-dir output
```

Для нескольких частей создаются файлы с суффиксом `-combined`.

Для разделения текста по спикерам добавьте `--speakers`:

```bash
transcribe-local input/meeting.m4a --output-dir output --speakers
```

Если число участников известно, передайте его явно:

```bash
transcribe-local input/meeting.m4a --output-dir output --speakers --speaker-count 4
```

В этом режиме создаются `meeting-speakers.txt` и `meeting-speakers.json`.
Определяются условные подписи `Спикер 1`, `Спикер 2` и т. д.; имена людей
модель не определяет. Первый запуск скачивает Community-1, последующие проходят
локально из кэша.

Повторная проверка пропущенных интервалов включена по умолчанию. Она повышает
полноту, но заметно увеличивает время обработки. Отключение:

```bash
transcribe-local input/meeting.m4a --output-dir output --no-gap-recovery
```

Обработка тихих голосов по умолчанию работает в режиме `auto`: громкость каждой
части измеряется отдельно, и нормализация включается только для тихих файлов.
Принудительное включение или выключение:

```bash
transcribe-local input/meeting.m4a --output-dir output --audio-enhancement on
transcribe-local input/meeting.m4a --output-dir output --audio-enhancement off
```

Для ручного сравнения модели CTC с основной RNNT:

```bash
transcribe-local input/meeting.m4a --output-dir output --model v3_e2e_ctc
```

При первом выборе CTC её веса будут загружены отдельно. Не делайте вывод по
одной фразе: сравнивайте модели на одном и том же репрезентативном фрагменте.

По умолчанию CLI использует batch size 2. На Mac M1 он сначала пробует MPS;
если long-form инференс на MPS завершается ошибкой, весь файл автоматически
повторяется на CPU. Для принудительного CPU:

```bash
transcribe-local input/meeting.mp4 --output-dir output --device cpu
```

## Формат результата

`meeting.txt` содержит сегменты в виде:

```text
[00:00:03.120 --> 00:00:17.840] Добрый день. Начинаем встречу.
```

JSON-контракт версии 1.3:

```json
{
  "schema_version": "1.3",
  "input": {
    "path": "/absolute/path/meeting.webm",
    "name": "meeting.webm",
    "format": "webm",
    "size_bytes": 123456,
    "parts": [
      {
        "index": 1,
        "path": "/absolute/path/meeting.webm",
        "name": "meeting.webm",
        "format": "webm",
        "size_bytes": 123456,
        "start": 0.0,
        "end": 1800.0,
        "duration_seconds": 1800.0,
        "input_loudness_lufs": -21.4,
        "enhancement_applied": true
      }
    ]
  },
  "processing": {
    "model": "v3_e2e_rnnt",
    "mode": "longform",
    "device_requested": "auto",
    "device_used": "cpu",
    "cpu_fallback_used": false,
    "batch_size": 2,
    "audio": {
      "sample_rate_hz": 16000,
      "channels": 1,
      "codec": "pcm_s16le",
      "enhancement_mode": "auto",
      "enhancement_applied": true
    },
    "diarization": {
      "enabled": false,
      "model": null,
      "device_used": null,
      "num_speakers_requested": null,
      "num_speakers": null
    },
    "gap_recovery": {
      "enabled": true,
      "device_used": "cpu",
      "recovered_segments": 5
    },
    "started_at": "2026-07-15T12:00:00+00:00",
    "completed_at": "2026-07-15T12:05:00+00:00",
    "elapsed_seconds": 300.0
  },
  "text": "Добрый день. Начинаем встречу.",
  "segments": [
    {
      "start": 3.12,
      "end": 17.84,
      "speaker": null,
      "text": "Добрый день. Начинаем встречу."
    }
  ]
}
```

## Проверка без загрузки моделей

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Критерий готовности

Одна команда принимает один или несколько `.webm`, `.mp4`, `.mp3` или `.m4a`,
объединяет части в заданном порядке, нормализует аудио через FFmpeg,
восстанавливает подозрительные пропуски и создаёт корректные `TXT`, `DOCX` и
`JSON` со сквозными таймкодами и опциональными спикерами.

## Сборка продуктового приложения

Сначала один раз соберите минимальный FFmpeg 7.1 под LGPL. Скрипт скачивает
официальный архив с `ffmpeg.org`, проверяет SHA-256 и не включает сеть,
внешние библиотеки, GPL- или nonfree-компоненты:

```bash
scripts/build_ffmpeg_lgpl.sh
```

Затем соберите автономное приложение:

```bash
REBUILD_RUNTIME=1 scripts/build_app_bundle.sh
```

Результат: `dist/Транскрибатор.app`. Внутри находятся arm64 Python-runtime,
модели GigaAM, FFmpeg, privacy-документ, лицензии пакетов и исходный архив
FFmpeg. Повторная упаковка без пересборки runtime:

```bash
scripts/build_app_bundle.sh
```

По умолчанию применяется локальная ad-hoc подпись только для разработки.
Передаваемый коллегам релиз собирается воспроизводимым Python 3.12.10
окружением и подписывается сертификатом Developer ID:

```bash
scripts/prepare_python_toolchain.sh
scripts/prepare_release_environment.sh
RELEASE_BUILD=1 REBUILD_RUNTIME=1 \
  SIGN_IDENTITY="Developer ID Application: ..." \
  scripts/build_app_bundle.sh
```

После подписи создаётся только нотариализованный DMG:

```bash
NOTARY_PROFILE="transcriber-notary" scripts/build_product_dmg.sh
```

Скрипт требует Developer ID, отправляет `.app` и DMG в Apple notary service,
прикрепляет tickets, проверяет Gatekeeper и создаёт SHA-256/manifest. Без
`NOTARY_PROFILE` финальный образ намеренно не создаётся. Постоянный bundle ID:
`com.ainikitadanik.transcriber`.

Готовый DMG содержит arm64 Python runtime, FFmpeg, модели GigaAM RNNT/CTC,
лицензии, установщик и откат. Приложение устанавливается в
`~/Applications/Транскрибатор.app`, поэтому admin-права не нужны. Базовая
файловая транскрибация подтверждена на bundled GigaAM без Hugging Face token
и без отправки аудио или текста наружу. Realtime-контур реализован, но до
передачи должен пройти signed clean-Mac acceptance системного звука и
микрофона.

Модели pyannote не входят в поставку. Они нужны только для опционального
разделения по спикерам; пользователь отдельно принимает их условия и вводит
личный Hugging Face Read-токен.

## Текущий release status

В `dist/Транскрибатор.app` находится проверенный internal candidate, но он
подписан ad hoc. Его нельзя выдавать за готовый внешний релиз. Финальный DMG
появится после предоставления release-owner сертификата Developer ID и
notary-профиля. Актуальные gates перечислены в
`documentation/14_PRODUCT_READINESS_HEALTH_CHECK.md`.

Для разовой внутренней проверки доверенным администратором можно собрать
явно маркированный образ:

```bash
scripts/build_internal_admin_dmg.sh
```

Такой файл содержит `INTERNAL-UNNOTARIZED` в имени, не является публичным
релизом и запускается только через штатный administrator override macOS.

История изменений: [CHANGELOG.md](CHANGELOG.md).
