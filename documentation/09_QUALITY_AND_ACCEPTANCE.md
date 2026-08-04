# Качество и приёмка

Статус: обязательный quality gate
Актуально на: 2026-07-28

## Принцип

Количество пройденных unit tests само по себе не означает готовность продукта.
Проверка выбирается по риску изменения и включает реальные артефакты там, где
mock не подтверждает пользовательский результат.

## Уровни проверки

### L1. Статическая проверка

- синтаксис и импорт;
- формат конфигурации и plist;
- отсутствие случайных секретов;
- diff review;
- проверка ссылок и идентификаторов документации.

### L2. Unit

- чистая бизнес-логика;
- валидация;
- контракты данных;
- bounded buffers;
- сообщения ожидаемых ошибок.

### L3. Integration

- Flask endpoints;
- pipeline с подменёнными тяжёлыми моделями;
- storage/environment lifecycle;
- build-script invariants;
- экспорт реального DOCX.

### L4. Local end-to-end

- реальный FFmpeg;
- реальная GigaAM model;
- реальный spoken sample;
- TXT/JSON/DOCX;
- offline mode;
- MPS/CPU поведение.

### L5. Packaged acceptance

- запуск `.app` двойным нажатием;
- корректная идентичность и разрешения;
- first-run system-audio и microphone prompts принимаются стандартным
  пользователем без admin credentials;
- работа без dev environment;
- чистая user account;
- Gatekeeper;
- отсутствие сетевой передачи данных.

## Матрица обязательных проверок

| Изменение | Минимум |
| --- | --- |
| чистая функция core | L1 + L2 |
| pipeline/ASR/export | L1 + L2 + L3 + L4 |
| web UI/API | L1 + L2/L3 + browser/manual smoke |
| storage/token/privacy | L1 + L2 + L3 + targeted security check |
| realtime buffer/capture | L1 + L2 + L3 + manual permission acceptance |
| realtime ASR | L1–L4 + 30-minute scenario |
| packaging/dependency | L1–L5 |
| release | все применимые уровни |
| документация без кода | link/consistency review + source verification |

Для UI polish browser/manual smoke включает 1440, 1280, 1024, 820, 640 и
480 px, оба mode panels, keyboard tabs/focus, empty/short/150+ filename,
multi-part, loading/error/done и фактические capture states. Для каждого
viewport проверяется `document.scrollWidth === document.clientWidth`.

Playwright screenshots хранятся в `output/playwright/` как evidence и не
подменяют функциональные тесты. Pause/live ASR/realtime export указываются
`N/A`, пока соответствующий backend не реализован.

## Автоматический baseline

Текущий suite расположен в `tests/` и покрывает:

- core pipeline и JSON schema 1.3;
- model storage/offline lifecycle;
- Flask upload/status/result flows;
- realtime PCM buffer и helper routing;
- packaging identity, entitlement и LGPL FFmpeg invariants.

Internal candidate на общей ветке прошёл 72/72 автоматических теста
2026-07-28. Отдельный frozen-runtime offline GigaAM file-ASR smoke также
прошёл. Эти результаты не заменяют L5 signed no-admin/Gatekeeper/TCC
acceptance.

Каноническая команда:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Если используется `pytest`, результат должен быть эквивалентен. Новое поведение
должно добавлять тест, а не только менять старое ожидание.

## Контрольный набор аудио

Нужен отдельный не включаемый в git набор с разрешённым использованием:

- короткая чистая речь;
- 30–60 минут рабочей встречи;
- тихий голос;
- два и более спикера;
- длинная пауза без сигнала;
- пропуск VAD при наличии речи;
- несколько последовательных файлов;
- шум и перекрывающаяся речь;
- system audio + microphone realtime.

Для каждого примера нужен ожидаемый тип результата и известные ограничения.
Дословный golden text вводится только там, где он реально размечен.

## Приёмка файловой транскрибации

1. Все части расположены в правильном порядке.
2. Таймкоды монотонны и не выходят за длительность.
3. TXT, JSON, DOCX созданы и открываются.
4. JSON проходит schema assertions.
5. Metadata отражает фактические device, fallback, model и параметры.
6. Diarization не подставляет имена.
7. Token отсутствует в output, status и logs.
8. Временный normalized audio удалён.
9. Ошибка одного формата не оставляет задачу в ложном `done`.
10. На MPS fallback повторяет обработку целиком и фиксируется в metadata.

## Приёмка UX

- базовый сценарий выполняется без инструкции разработчика;
- default-параметры дают ожидаемый безопасный путь;
- progress не показывает 100% до экспорта;
- ошибка содержит следующее действие;
- пользователь понимает локальность и роль HF token;
- папки открываются только из allowlist;
- незавершённый realtime явно обозначен.

## Блокирующие дефекты

- аудио/текст уходит наружу;
- token сохраняется или попадает в лог;
- UI слушает не loopback;
- результат `done` без полного комплекта выходов;
- несовместимое изменение JSON без версии;
- изменение bundle ID без ADR;
- realtime пишет PCM на диск;
- внешняя сборка не проходит подпись/notarization/Gatekeeper;
- лицензии поставки не соответствуют включённым компонентам.
- хотя бы один обязательный runtime Mach-O требует macOS новее заявленной;
- зависимость включает telemetry/metrics по умолчанию;
- встроенные модели присутствуют, но clean-account runtime их не разрешает;
- целевой no-admin пользователь не может запустить обязательный audio capture.

## Evidence bundle при завершении задачи

Каждая существенная задача должна оставить:

- что изменено;
- какие требования/ADR затронуты;
- список изменённых файлов;
- команды и результаты проверок;
- ручные проверки;
- что не проверено;
- известные риски;
- следующий необходимый decision, если он есть.
