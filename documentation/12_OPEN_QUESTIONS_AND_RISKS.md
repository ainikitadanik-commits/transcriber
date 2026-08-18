# Открытые вопросы и риски

Статус: живой реестр
Актуально на: 2026-08-12

## Правила

- открытый вопрос не закрывается предположением;
- при принятии решения создаётся ADR и здесь ставится ссылка;
- риск закрывается только доказательством, а не наличием кода;
- приоритет: `P0` блокирует выпуск, `P1` блокирует этап, `P2` контролируется.

## Открытые вопросы

| ID | Приоритет | Вопрос | Что нужно для решения |
| --- | --- | --- | --- |
| OQ-001 | P1 | Распознавать system/microphone раздельно или микшировать? | benchmark качества, latency и нагрузки; ADR |
| OQ-002 | P1 | Какие window, overlap и commit horizon выбрать для realtime? | измерения на MPS/CPU на контрольной встрече |
| OQ-003 | P1 | Какова точная семантика Pause? | UX-решение и state-machine test |
| OQ-004 | P1 | Расширять JSON 1.x для realtime или вводить 2.0? | проект контракта и compatibility review |
| OQ-005 | P0 release | Кто правообладатель собственного кода и каковы условия распространения? | юридическое решение |
| OQ-006 | P0 release | Какая Developer ID identity используется? | сертификат и release owner |
| OQ-007 | P1 | Как устанавливать product `.app` в user-local Applications из DMG? | чистая Mac acceptance |
| OQ-008 | P2 | Как ротировать logs и очищать брошенные upload directories? | storage policy и privacy review |
| OQ-009 | P2 | Нужен ли постоянный job history и безопасная отмена? | product intent после realtime |
| OQ-010 | P1 | Как разрешать конфликт фиксированного порта 7860? Реальный конфликт подтверждён на Mac коллеги после установки 0.2.4 | BL-001: динамический loopback-порт, перенос порта в runtime marker и packaged update/conflict/cleanup tests |
| OQ-011 | P1 | Какой минимальный контрольный аудионабор допустимо хранить для QA? | права на записи и fixture policy |
| OQ-012 | P2 | Когда прекращать fallback к `~/.cache/gigaam`? | миграция и telemetry-free verification |
| OQ-013 | P0 | Проходит ли Core Audio Tap system-audio prompt на реальном корпоративном no-admin Mac? | ADR-013 signed spike и evidence bundle |
| OQ-014 | P1 | Принимается ли реализованный отдельный AVAudioEngine microphone-контур? | signed live latency/device-switch test |

## Риски

| ID | Приоритет | Риск | Текущая мера | Остаток |
| --- | --- | --- | --- | --- |
| R-001 | P0 | Внешний `.app` не проходит Gatekeeper | локальная ad-hoc проверка | нет Developer ID, bottom-up signing, notarization |
| R-002 | P0 | System audio недоступен целевому no-admin пользователю | Core Audio Tap и отдельный mic-контур реализованы; ADR-013 Proposed | нужен signed dual-source TCC test; MDM не обходится |
| R-003 | P1 | Realtime latency неприемлема на M1 | окна до 25 сек запланированы | нет benchmark |
| R-004 | P1 | Дубли/потери на overlap | scheduler и deterministic dedup покрыты unit tests | нужен 30-минутный live benchmark |
| R-005 | P1 | Два источника удваивают нагрузку или ухудшаются при mix | потоки пока раздельные | нет ADR |
| R-006 | P0 | Dependency telemetry нарушает local-only policy | pyannote metrics отключаются до импорта; base mode не требует pyannote models, HF token или сети | нужен packaged network observation для optional diarization |
| R-007 | P1 | Product build поддерживает меньше контейнеров, чем README | LGPL/network-disabled capability audit проходит | нужна полная artifact format matrix |
| R-008 | P2 | Общий singleton job ограничивает надёжность | запрет второй задачи | state теряется при restart |
| R-009 | P2 | Общая output-папка создаёт коллизии имён | комплекты получают общий свободный индекс; существующие результаты не перезаписываются | повторить packaged acceptance одинаковых имён |
| R-010 | P2 | Документация и UI обещают больше, чем доказано | realtime core/API/UI реализованы | не объявлять product-ready до signed TCC и 30-минутного E2E |
| R-011 | P1 | Лицензии меняются вместе с dependency graph | auto collection + ledger | пересобирать каждый релиз |
| R-012 | P2 | Логи/inputs растут без ограничений | Finder access | нет retention policy |
| R-013 | P1 | Качество оценивается по нерепрезентативному примеру | требование control set | набора пока нет |
| R-014 | P0 | Встроенные GigaAM weights не используются на чистом Mac | resolver исправлен; frozen-runtime offline file-ASR smoke PASS | повторить на чистой внешней учётной записи |
| R-015 | P1 | Product FFmpeg не исполняет audio enhancement | LGPL/network-disabled capability audit PASS, нужные filters/muxer/protocols присутствуют | повторить на final signed artifact |
| R-016 | P1 | Новая оболочка подключается к runtime старой/backup сборки на порту 7860 | frozen `/api/health` exact build/instance PASS | packaged conflict, shutdown и update test |
| R-017 | P1 | TCC denial показывается как общий сбой | structured denied/managed_denied покрыты тестами | live localized TCC/MDM evidence отсутствует |
| R-018 | P0 | Artifact не запускается на заявленной macOS 15+ | 417 Mach-O arm64/minOS <= 15 audit PASS | реальный запуск на чистой macOS 15 |
| R-019 | P0 | License bundle не соответствует runtime | 41 Python package сопоставлен с license material | повторить audit на final signed artifact |
| R-020 | P1 | Старый runtime или другое локальное приложение занимает 7860 и блокирует запуск `.app` | строгая проверка build/instance не позволяет подключиться к чужому сервису; документирован ручной cleanup | фиксированный порт остаётся single point of failure; реализовать BL-001 и packaged acceptance |

## Известные расхождения на дату фиксации

- `README.md` всё ещё начинает пользовательский путь с legacy release 0.1.1 и
  `.command`, тогда как целевой путь уже product `.app`;
- internal release 0.2.2 опубликован; исправляющая версия 0.2.3 готовится в
  `pyproject.toml` и `Info.plist`;
- realtime core/API/UI и export реализованы, но signed dual-source TCC
  acceptance отсутствует;
- internal candidate подписан ad hoc и не проходит внешний
  notarization/Gatekeeper release gate;
- clean corporate no-admin/MDM acceptance не выполнен;
- base file mode работает offline на bundled GigaAM без pyannote models,
  HF token или сети; модели pyannote остаются optional gated dependency только
  для diarization;
- `docs/PRODUCT_SPEC.md` и `docs/REALTIME_ROADMAP.md` остаются полезными, но их
  нормы теперь собраны и уточнены в этом каталоге.

Эти пункты не надо «исправлять по пути» без задачи; они служат входом для
следующих этапов roadmap.
