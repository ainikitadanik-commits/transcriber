# Product readiness health-check

Статус: канонический baseline, release `NO-GO`
Дата проверки: 2026-07-20
Проверенный source state: `main@460eb11`
Целевая версия: product `.app` 0.2.x

## Решение тимлида

Технический каркас приложения собран, но UI polish и финальная упаковка пока
не должны маскировать фундаментальные дефекты. До UI допускается только работа,
не обещающая готовый realtime. До передачи коллегам обязательны P0/P1 ниже.

Жёсткий критерий аудитории: установка, первый запуск и выдача доступов должны
выполняться стандартным пользователем без admin credentials. Инструкция
«включите разрешение вручную» не считается решением.

## Как проведена проверка

Независимые read-only проверки выполнили роли:

- системный аналитик — требования, ADR, privacy и readiness;
- дебаггер — тесты, artifact/runtime, TCC, port и ошибки;
- лид backend/frontend — capture flow, API/UI и lifecycle;
- упаковка продукта — bundle, nested code, models, FFmpeg и distribution.

Тимлид воспроизвёл запуск установленного `.app` и реальный
`POST /api/realtime/start`.

## Подтверждённый baseline

- Git clean; `main == origin/main == 460eb11`.
- 37/37 автоматических тестов проходят.
- `dist/Транскрибатор.app` существует, arm64, version 0.2.0, bundle ID
  `com.ainikitadanik.transcriber`.
- В bundle присутствуют PyInstaller runtime, GigaAM RNNT/CTC weights,
  LGPL FFmpeg без network и license materials.
- FFmpeg реально преобразует M4A в `pcm_s16le` через pipe.
- Native helper synthetic self-test выдаёт ненулевой system/microphone PCM.
- Flask слушает loopback.
- Установленная и локальная `.app` проходят локальный
  `codesign --verify --deep --strict`.

Эти доказательства подтверждают каркас, но не product acceptance.

## Release blockers

### P0. Audio permission не работает у целевой аудитории

Реальный packaged start завершился:

```text
status=error
system_audio=false
microphone=false
ScreenCaptureKit: userDeclined
```

Падение происходит до отдельной проверки microphone. Текущий путь зависит от
Screen & System Audio Recording, которое пользователь не может включить.

Решение: [ADR-013](11_ARCHITECTURE_DECISIONS.md) и signed Core Audio Tap spike.
Приложение должно получить отдельный system-audio prompt без admin credentials
и без ручного Screen Recording. MDM-запрет не обходится.

### P0. Нет стабильной release identity

Текущий app подписан ad hoc:

- `TeamIdentifier` отсутствует;
- designated requirement привязан к CDHash и меняется после rebuild;
- Developer ID/notarization/stapling отсутствуют;
- product DMG 0.2.0 отсутствует.

Следствие: нельзя доказать continuity TCC permissions и Gatekeeper acceptance.

### P0. Нарушен privacy-инвариант telemetry-free

В bundled dependency `pyannote.audio 4.0.7` metrics включены по умолчанию.
Приложение не устанавливает `PYANNOTE_METRICS_ENABLED=0` до импорта pyannote.
Это блокирует SEC-003 до исправления и наблюдаемого network test.

### P0. Bundle models могут не загрузиться на чистом Mac

Native shell задаёт путь к моделям в Resources, но `configure_storage()`
безусловно заменяет его на user Application Support. На Mac разработчика это
маскируется кэшем; на чистой учётной записи bundled weights могут не
разрешиться.

### P0. Artifact не соответствует minimum macOS

`Info.plist` и native shell заявляют macOS 15.0, но фактический embedded
Python framework и product FFmpeg имеют `minos 26.0`. Следовательно, текущий
artifact нельзя передавать коллегам на macOS 15–25. Runtime и FFmpeg должны
быть пересобраны в совместимом окружении, а release gate — проверять каждый
Mach-O.

### P0. License bundle неполон

В runtime присутствуют `python-docx` и `transformers`, но их лицензии не
найдены в release license bundle. NFR-LIC-001 не выполнен до полной
artifact-to-license сверки.

## Stage blockers

### P1. Product FFmpeg расходится с pipeline

Audio enhancement использует `ebur128`, `highpass`, `loudnorm` и muxer `null`,
которых нет в product FFmpeg. `auto` молча пропускает enhancement, `on`
завершается ошибкой.

### P1. Runtime не имеет строгого ownership

Обнаружен сценарий, когда новая shell подключается к runtime backup-сборки на
`127.0.0.1:7860`. Нужны instance/build ID, single-instance ownership, полный
HTTP health response и детерминированный shutdown.

### P1. Permission error model недостаточна

Классификация ищет английские `permission/denied`; локализованный
`userDeclined` становится общим сообщением. Нужны стабильные коды состояний,
разделение `denied`/`managed_denied`/device error и журналирование без
чувствительных данных.

### P1. UI обещает отсутствующий realtime ASR

Реализованы capture и bounded RAM buffers, но не scheduler, live text, Pause,
finalization и export. До реализации UI должен честно обозначать capture
diagnostic или скрыть этот режим.

## Порядок работ

### Gate A — до UI polish

1. Отключить pyannote metrics до импорта и добавить regression/network check.
2. Исправить resolver bundled GigaAM models и clean-account test.
3. Дополнить product FFmpeg и artifact-level Auto/On tests.
4. Исправить single-instance, port ownership и shutdown.
5. Принять ADR-013 через signed Core Audio Tap spike на no-admin Mac.
6. Ввести permission/error state model.
7. Скрыть или честно переименовать незавершённый realtime.

Только после Gate A выполняется запрошенный UI polish.

### Gate B — до передачи коллегам

1. Интегрировать принятый audio capture contour и отдельный microphone input.
2. Пересобрать runtime/FFmpeg с minimum macOS 15.0 и проверить все Mach-O.
3. Пересобрать полный license bundle из фактического artifact.
4. Получить Developer ID Application.
5. Подписать nested Mach-O bottom-up, затем внешний `.app`.
6. Notarize, staple и проверить Gatekeeper.
7. Собрать product DMG с установкой в `~/Applications` без admin.
8. Пройти L5 на чистой no-admin учётной записи: prompts, bundled models,
   packaged ASR, offline repeat, Stop/Quit/restart/update.
9. Выполнить network/token/log/PCM и license review.
10. Синхронизировать README, changelog и release notes.

## Что сейчас нельзя называть готовым

- no-admin audio capture;
- local-only/privacy compliance;
- stable permissions между обновлениями;
- clean-account packaged transcription;
- audio enhancement в product artifact;
- realtime transcription и export;
- product DMG 0.2.0;
- совместимость текущего artifact с macOS 15–25;
- полноту license bundle;
- Gatekeeper/notarized external release;
- update/rollback acceptance.

## Недоступные доказательства

- TCC database и unified macOS log недоступны текущему standard user;
- Developer ID identity отсутствует;
- чистый корпоративный Mac с действующим MDM не предоставлен;
- notarization и Gatekeeper release test не выполнялись;
- полный ASR/network capture из установленного bundle не выполнялся.

Эти пункты не закрываются предположениями и остаются release evidence gates.
