# Упаковка и выпуск

Статус: операционная спецификация
Актуально на: 2026-07-20
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
- product build использует специально собранный FFmpeg;
- product FFmpeg поддерживает локальные протоколы `file` и `pipe`, а также
  muxer `pcm_s16le`, необходимый GigaAM для передачи raw PCM через stdout;
- модели GigaAM проверяются до копирования;
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
- `codesign --verify --deep --strict` успешен;
- notarization/stapling успешны для внешнего релиза;
- `hdiutil verify` успешен;
- SHA-256 записан;
- проверена чистая user account / Mac без dev environment.

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
