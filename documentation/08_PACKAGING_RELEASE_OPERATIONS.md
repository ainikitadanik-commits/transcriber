# Упаковка и выпуск

Статус: операционная спецификация
Актуально на: 2026-07-28
Текущая версия кода: 0.2.0
Последний опубликованный релиз: 0.1.1

## Два поколения упаковки

### Legacy 0.1.1

`packaging/build_macos.sh` создаёт user-local runtime и DMG с `.command`
установщиком. Этот путь опубликован в private GitHub release и остаётся
подтверждённым для 0.1.1.

### Product `.app` 0.2.0

`scripts/build_app_bundle.sh` создаёт:

- `Транскрибатор.app`;
- постоянный native executable;
- встроенный PyInstaller runtime;
- GigaAM RNNT/CTC weights;
- минимальный LGPL FFmpeg;
- privacy и license materials.

Это целевой путь развития. Legacy packaging поддерживается до подтверждённого
релиза `.app`, но новые продуктовые изменения не должны ориентироваться на
`.command` как на конечный UX.

## Постоянные параметры продукта

| Параметр | Значение |
| --- | --- |
| product name | `Транскрибатор` |
| bundle ID | `com.ainikitadanik.transcriber` |
| minimum macOS | 15.0 |
| architecture | arm64 / Apple Silicon |
| install target | `~/Applications/Транскрибатор.app` |
| data root | `~/Library/Application Support/Транскрибатор` |
| local UI | `http://127.0.0.1:7860` |

## Требования к сборке

- сборка выполняется из чистого проверяемого source state;
- версия синхронизирована в `pyproject.toml`, `Info.plist`, changelog и
  component ledger;
- GigaAM dependency остаётся закреплённой на конкретный commit;
- runtime включает web templates/static и ресурсы python-docx;
- каждый вложенный Mach-O имеет minimum macOS не выше заявленных 15.0;
- product build использует специально собранный FFmpeg;
- product FFmpeg поддерживает локальные протоколы `file` и `pipe`, а также
  muxer `pcm_s16le`, необходимый GigaAM для передачи raw PCM через stdout;
- модели GigaAM проверяются до копирования;
- clean-account test подтверждает, что runtime использует модели из
  `Contents/Resources/models/gigaam`, а не только developer cache;
- pyannote models не встраиваются и получаются пользователем;
- license bundle соответствует фактическому runtime;
- итоговый `.app` проходит `codesign --verify`.

## Подпись

Локальная приёмочная сборка MAY использовать ad-hoc identity `-`.

Внешний релиз MUST использовать:

1. `Developer ID Application`;
2. hardened runtime;
3. подпись всех вложенных Mach-O;
4. подпись итогового `.app`;
5. notarization;
6. stapling;
7. проверку Gatekeeper на чистой учётной записи.

На момент фиксации постоянная signing identity отсутствует, поэтому 0.2.0 не
считается готовой к внешнему распространению.

Internal candidate собран воспроизводимым user-local Python toolchain.
Artifact audit проверил 417 Mach-O: все arm64 и имеют minimum macOS не выше
15.0. Это закрывает структурный artifact gate, но не заменяет запуск на чистой
macOS 15.

Подпись выполняется bottom-up: каждый вложенный Mach-O получает Developer ID
и hardened runtime до подписи внешнего `.app`. `codesign --deep` не является
заменой явной подписи вложенных бинарников.

## DMG

Целевой DMG:

- содержит подписанное и нотариализованное `.app`;
- позволяет установку в user-local `~/Applications`;
- не требует администратора;
- использует ASCII-safe имя release asset;
- имеет опубликованный SHA-256;
- проходит `hdiutil verify`;
- содержит краткую установочную инструкцию и license materials.

Точный UX копирования `.app` в user-local Applications требует финальной
приёмки и может отличаться от legacy `.command` установщика.

## Версионирование

Используется SemVer на уровне приложения:

- patch — исправление без изменения контракта;
- minor — обратно совместимая функция;
- major — несовместимое изменение пользовательского или data-контракта.

JSON schema версионируется отдельно и не обязана совпадать с версией приложения.

## Evidence internal candidate 2026-07-28

- 72/72 автоматических теста проходят;
- frozen runtime `/api/health` возвращает точные `build_id` и `instance_id`;
- offline file-ASR smoke с `HF_HUB_OFFLINE=1`, explicit bundled GigaAM path и
  без token завершился `done`: 10-секундный WAV дал TXT 284 B, JSON 2.1 KiB и
  DOCX 38 KiB, 1 сегмент/136 символов, `processing.mode=local_windows`,
  `device=cpu`;
- 417 Mach-O проходят arm64/minOS <= 15 audit;
- product FFmpeg проходит LGPL/network-disabled capability audit;
- 41 фактически включённый Python package сопоставлен с license material;
- подпись candidate только ad hoc.

Это внутренний candidate, не transferable product release.

## Release checklist

### Source

- рабочее дерево просмотрено;
- версия обновлена во всех местах;
- changelog содержит только фактические изменения;
- документация синхронизирована;
- secret scan выполнен.

### Tests

- unit/integration suite прошла;
- real file smoke test прошёл;
- packaged app file transcription прошла;
- realtime acceptance выполнена, только если функция объявляется готовой;
- offline повторный запуск прошёл.

### Artifact

- component ledger пересобран;
- лицензии включены;
- лицензии `python-docx`, `transformers` и всех остальных реально включённых
  компонентов найдены в release license bundle;
- все Mach-O проходят minimum-OS audit для macOS 15.0;
- `codesign --verify --deep --strict` успешен;
- notarization/stapling успешны для внешнего релиза;
- `hdiutil verify` успешен;
- SHA-256 записан;
- проверена чистая user account / Mac без dev environment.
- system audio и microphone разрешаются системными пользовательскими prompt
  без admin credentials; ручное изменение защищённых настроек не является
  допустимым install step;
- bundled GigaAM weights реально разрешаются на чистой учётной записи;
- dependency telemetry отключена до импорта библиотек.

### Publication

- release notes не обещают незавершённые функции;
- asset name ASCII-safe;
- tag указывает на проверенный commit;
- репозиторий и release visibility соответствуют принятому контуру;
- download link проверен;
- rollback artifact сохранён.

## Rollback

Каждый релиз должен сохранять:

- tag;
- release artifact;
- SHA-256;
- release notes;
- известные ограничения;
- инструкцию возврата к предыдущей версии без удаления пользовательских данных.

Обновление не должно автоматически удалять `input`, `output` и model cache.
