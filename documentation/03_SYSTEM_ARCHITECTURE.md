# Архитектура системы

Статус: каноническая архитектура
Актуально на: 2026-07-28

## Контекст

Приложение выполняется целиком на одном Mac. Базовая файловая транскрибация
использует bundled GigaAM offline и не требует pyannote models, HF token или
сети. Внешняя сеть допустима только для явно включённой diarization:
пользователь принимает условия gated pyannote-модели и временно вводит Read
token. Обработка записей и текста находится внутри локальной границы доверия.

## Компоненты

| Компонент | Реализация | Ответственность |
| --- | --- | --- |
| macOS shell | `native/realtime_capture.swift` | идентичность `.app`, menu bar, запуск runtime, системные разрешения, realtime capture |
| локальный runtime | PyInstaller + Python | Flask UI, pipeline, модели и экспорт |
| web UI | Flask, HTML, CSS, JS | выбор параметров, запуск, статусы, результаты |
| CLI | `transcriber.cli` | технический файловый сценарий |
| pipeline | `transcriber.core` | валидация, FFmpeg, ASR, recovery, diarization, экспорт |
| model/storage layer | `transcriber.models` | пути данных, кэши и получение моделей |
| realtime capture | `transcriber.realtime` | дочерний capture-процесс, события и PCM-буферы |
| realtime ASR | `transcriber.realtime_asr`, `transcriber.gigaam_realtime` | окна, overlap/dedup и локальный GigaAM adapter |
| realtime service | `transcriber.realtime_service` | lifecycle, live state, finalization и export |
| media layer | FFmpeg 7.1 | локальная нормализация контейнеров и PCM |
| ASR | GigaAM | long-form распознавание |
| VAD/diarization | pyannote | сегментация речи и условные спикеры |

## Процессная модель установленного приложения

1. Пользователь открывает `Транскрибатор.app`.
2. executable `Transcriber` с bundle ID
   `com.ainikitadanik.transcriber` проверяет локальный порт.
3. Если собственный runtime ещё не запущен, shell запускает
   `transcriber-runtime --no-browser`.
4. Runtime поднимает Flask на `127.0.0.1:7860`.
5. Shell открывает интерфейс в браузере и остаётся в menu bar.
6. При realtime shell запускается повторно как capture helper и пишет события
   и два PCM-потока в pipes родительского Python-процесса.
7. Завершение из меню останавливает дочерний runtime.

## Файловый поток данных

```text
локальный файл(ы)
  -> input/<job-id>/<part>/
  -> FFmpeg: mono PCM 16 kHz
  -> при нескольких частях: единый WAV в temp
  -> GigaAM long-form ASR
  -> optional gap recovery
  -> optional pyannote diarization
  -> Segment[]
  -> TXT + JSON 1.3 + DOCX
  -> output/
```

Нормализованные WAV и recovery-чанки создаются во временном каталоге и должны
исчезать после выхода из pipeline.

## Realtime-поток

```text
Core Audio Tap system audio ---> resample mono 16 kHz ---> pipe ---> PCMBuffer
AVAudioEngine microphone ------> resample mono 16 kHz ---> pipe ---> PCMBuffer
                                                               |
                                             bounded window scheduler
                                                               |
                                                   GigaAM short ASR
                                                               |
                                                live state + local export
```

Весь внутренний контур реализован и покрыт автоматическими тестами. Его
product-ready статус остаётся заблокированным до signed TCC dual-source
acceptance на чистом корпоративном no-admin Mac.

## Хранилище

Канонический корень:

```text
~/Library/Application Support/Транскрибатор
```

| Путь | Содержимое | Жизненный цикл |
| --- | --- | --- |
| `input/` | сохранённые пользовательские загрузки | пользователь удаляет вручную |
| `output/` | TXT, JSON, DOCX | пользователь удаляет вручную |
| `models/gigaam/` | локальные веса при source-установке | сохраняются между запусками |
| `models/huggingface/` | optional gated pyannote cache для diarization | сохраняется между запусками |
| `logs/` | локальные журналы | политика ротации пока открыта |

В продуктовой `.app` веса GigaAM находятся также внутри Resources. Путь
передаётся runtime через `TRANSCRIBER_GIGAAM_MODELS_DIR`.

## Стабильные технические границы

- UI не получает произвольный доступ к файловой системе;
- endpoint открытия папки использует allowlist `input`/`output`;
- интерфейс не должен слушать `0.0.0.0`;
- capture helper не записывает исходный realtime PCM на диск;
- токен модели не проходит в pipeline распознавания;
- модельный и storage layer не должны зависеть от UI;
- формирование результата централизовано в `core`;
- native shell не реализует бизнес-логику транскрибации.

## Текущие ограничения архитектуры

- singleton `_job` допускает одну файловую задачу и теряется при перезапуске;
- нет постоянного каталога задач и восстановления незавершённой обработки;
- endpoint скачивания опирается на имя файла в общей `output/`;
- нет ротации логов;
- live signed Core Audio Tap + microphone TCC acceptance ещё не выполнен;
- realtime не прошёл 30-минутный packaged сценарий;
- проверки качества речи в основном требуют реальных аудиофикстур.

Эти ограничения не являются разрешением на случайную переработку. Их изменение
планируется через roadmap и ADR.

## Запрещённые архитектурные дрейфы

Без отдельного решения нельзя:

- переносить обработку в облако;
- открывать UI в локальную сеть;
- сохранять HF token;
- менять bundle ID;
- писать realtime PCM на диск «для удобства»;
- добавлять обязательную БД или аккаунт;
- удалять поддержку прежнего кэша без миграции;
- смешивать capture readiness и ASR readiness в одном статусе.
