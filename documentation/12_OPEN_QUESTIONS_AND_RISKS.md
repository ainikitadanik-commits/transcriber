# Открытые вопросы и риски

Статус: живой реестр
Актуально на: 2026-07-20

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
| OQ-010 | P2 | Как разрешать конфликт, если порт 7860 занят другим процессом? | process identity/health design |
| OQ-011 | P1 | Какой минимальный контрольный аудионабор допустимо хранить для QA? | права на записи и fixture policy |
| OQ-012 | P2 | Когда прекращать fallback к `~/.cache/gigaam`? | миграция и telemetry-free verification |
| OQ-013 | P0 | Проходит ли Core Audio Tap system-audio prompt на реальном корпоративном no-admin Mac? | ADR-013 signed spike и evidence bundle |
| OQ-014 | P1 | Какой отдельный microphone input-контур использовать после отказа от ScreenCaptureKit? | spike AVFoundation/Core Audio, latency и device-switch test |

## Риски

| ID | Приоритет | Риск | Текущая мера | Остаток |
| --- | --- | --- | --- | --- |
| R-001 | P0 | Внешний `.app` не проходит Gatekeeper | локальная ad-hoc проверка | нет Developer ID, bottom-up signing, notarization |
| R-002 | P0 | System audio недоступен целевому no-admin пользователю | ScreenCaptureKit возвращает `userDeclined`; ADR-013 Proposed | нужен signed Core Audio Tap spike; MDM не обходится |
| R-003 | P1 | Realtime latency неприемлема на M1 | окна до 25 сек запланированы | нет benchmark |
| R-004 | P1 | Дубли/потери на overlap | dedup предусмотрен спецификацией | алгоритм не реализован |
| R-005 | P1 | Два источника удваивают нагрузку или ухудшаются при mix | потоки пока раздельные | нет ADR |
| R-006 | P0 | Dependency telemetry нарушает local-only policy | HF telemetry отключена | pyannote metrics default включён; нужен runtime disable и network test |
| R-007 | P1 | Product build поддерживает меньше контейнеров, чем README | минимальный FFmpeg | нужна artifact format matrix |
| R-008 | P2 | Общий singleton job ограничивает надёжность | запрет второй задачи | state теряется при restart |
| R-009 | P2 | Общая output-папка создаёт коллизии имён | job inputs изолированы | outputs не namespaced |
| R-010 | P2 | Документация и UI обещают больше, чем код | realtime переименован в capture diagnostic; Pause/live text/export явно помечены как planned | повторять сверку перед каждым release |
| R-011 | P1 | Лицензии меняются вместе с dependency graph | auto collection + ledger | пересобирать каждый релиз |
| R-012 | P2 | Логи/inputs растут без ограничений | Finder access | нет retention policy |
| R-013 | P1 | Качество оценивается по нерепрезентативному примеру | требование control set | набора пока нет |
| R-014 | P0 | Встроенные GigaAM weights не используются на чистом Mac | weights физически включены в `.app` | `configure_storage()` перезаписывает bundle path пользовательским пустым каталогом |
| R-015 | P1 | Product FFmpeg не исполняет audio enhancement | базовые file/pipe/PCM проверки проходят | нет `ebur128`, `highpass`, `loudnorm` и muxer `null` |
| R-016 | P1 | Новая оболочка подключается к runtime старой/backup сборки на порту 7860 | loopback health endpoint | нет instance/build ownership и детерминированного shutdown |
| R-017 | P1 | Локализованный TCC denial показывается как общий сбой | есть общий friendly-error fallback | классификация зависит от английской строки, error не журналируется |
| R-018 | P0 | Artifact не запускается на заявленной macOS 15+ | shell имеет minimum 15.0 | embedded Python framework и FFmpeg требуют macOS 26.0 |
| R-019 | P0 | License bundle не соответствует runtime | автоматическая выборка собрала 68 файлов | не найдены лицензии включённых `python-docx` и `transformers` |

## Известные расхождения на дату фиксации

- `README.md` всё ещё начинает пользовательский путь с legacy release 0.1.1 и
  `.command`, тогда как целевой путь уже product `.app`;
- product version 0.2.0 есть в `pyproject.toml` и `Info.plist`, но внешний
  release 0.2.0 не опубликован;
- realtime UI/capture существует, но живого ASR и экспорта нет;
- текущий ScreenCaptureKit capture не проходит no-admin acceptance;
- pyannote metrics не отключены приложением;
- bundle models присутствуют, но clean-account resolver их перезаписывает;
- product FFmpeg не содержит фильтры, используемые audio enhancement;
- embedded Python/FFmpeg требуют macOS 26 при заявленной macOS 15+;
- license bundle не покрывает как минимум `python-docx` и `transformers`;
- `docs/PRODUCT_SPEC.md` и `docs/REALTIME_ROADMAP.md` остаются полезными, но их
  нормы теперь собраны и уточнены в этом каталоге.

Эти пункты не надо «исправлять по пути» без задачи; они служат входом для
следующих этапов roadmap.
