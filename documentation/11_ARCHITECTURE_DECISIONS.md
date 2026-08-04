# Журнал архитектурных решений

Статус: живой реестр ADR
Актуально на: 2026-07-20

## Правила

- новые записи добавляются, старые не переписываются задним числом;
- заменённое решение получает статус `Superseded by ADR-XXX`;
- решение содержит контекст, выбор, последствия и критерий пересмотра;
- открытый вопрос не оформляется как принятое решение.

## ADR-001. Полностью локальная обработка

Статус: Accepted

Контекст: записи рабочих встреч могут содержать чувствительные данные.

Решение: ASR, diarization, экспорт и realtime обработка выполняются на Mac
пользователя. Внешняя сеть допустима только для получения моделей.

Последствия: большая локальная поставка и зависимость скорости от Mac; облачный
fallback отсутствует.

Пересмотр: только при явной смене продуктовой модели и отдельном privacy review.

## ADR-002. Целевая платформа — macOS 15+ Apple Silicon

Статус: Accepted

Решение: первая продуктовая линия поддерживает arm64 Mac, macOS 15 и новее.

Последствия: можно использовать ScreenCaptureKit и не поддерживать несколько
архитектур сборки. Intel/другие ОС вне scope.

## ADR-003. Постоянная идентичность приложения

Статус: Accepted

Решение: bundle ID `com.ainikitadanik.transcriber`; native executable является
и shell приложения, и realtime capture helper.

Последствия: разрешения macOS относятся к одной идентичности. Смена bundle ID
ломает continuity разрешений.

## ADR-004. Локальный web UI внутри native shell

Статус: Accepted

Решение: native `.app` управляет локальным Python/Flask runtime и показывает UI
в собственном WKWebView-окне. Flask по-прежнему доступен только внутри Mac на
`127.0.0.1:7860`; системный браузер для интерфейса не запускается.

Последствия: переиспользуется существующий HTML/CSS/JS UI, но приложение имеет
отдельное окно и Dock-иконку. Порт и lifecycle остаются под контролем shell.
Внешние справочные ссылки открываются системно.

## ADR-005. GigaAM RNNT как default, CTC как option

Статус: Accepted

Решение: `v3_e2e_rnnt` — default; `v3_e2e_ctc` доступна для сравнения.
Зависимость GigaAM закреплена на проверенном commit.

Последствия: product defaults нельзя менять по одному примеру; нужна
репрезентативная проверка.

## ADR-006. MPS с полным CPU fallback

Статус: Accepted

Решение: auto выбирает MPS, а при runtime failure основная обработка файла
повторяется на CPU; факт записывается в metadata.

Последствия: надёжность выше, но ошибка MPS увеличивает общее время.

## ADR-007. Пользовательские данные в Application Support

Статус: Accepted

Решение: корень `~/Library/Application Support/Транскрибатор`; установка и
данные не требуют admin.

Последствия: update не должен удалять этот корень. Legacy GigaAM cache
поддерживается как fallback до миграции.

## ADR-008. JSON как машинный источник результата

Статус: Accepted

Решение: JSON schema 1.3 — структурированный контракт; TXT и DOCX являются
представлениями того же результата.

Последствия: несовместимые изменения требуют новой schema; DOCX не должен
добавлять отдельные факты.

## ADR-009. Realtime без виртуального аудиодрайвера

Статус: Accepted

Решение: system audio захватывается ScreenCaptureKit, microphone —
AVFoundation; оба источника передаются локальными pipes.

Последствия: нужны macOS permissions; исходный PCM не сохраняется; поддержка
ограничена выбранной платформой.

## ADR-010. Realtime позиционируется как near-real-time

Статус: Accepted

Решение: GigaAM обрабатывает короткие перекрывающиеся окна; UI и документация
не называют это истинным streaming ASR.

Последствия: нужны provisional/committed state, deduplication и измерение
latency.

## ADR-011. Product `.app` заменяет `.command` как основной UX

Статус: Accepted

Решение: `.command` остаётся legacy/internal fallback. Целевой пользовательский
путь — `Транскрибатор.app`.

Последствия: README и будущие release instructions должны перейти на `.app`
после его приёмки.

## ADR-012. Минимальная LGPL-сборка FFmpeg

Статус: Accepted

Решение: product build использует FFmpeg 7.1 без network, GPL, nonfree и
ненужных компонентов; исходники и лицензия включаются.

Последствия: список поддерживаемых контейнеров проверяется именно на этой
сборке, а не на Homebrew FFmpeg.

## ADR-013. System audio без Screen Recording permission

Статус: Proposed

Контекст: текущий ScreenCaptureKit-helper воспроизводимо получает
`userDeclined` у целевого пользователя. Ни пользователь, ни его коллеги не
имеют admin-прав и не могут вручную менять защищённую Screen & System Audio
Recording policy. Такой ручной шаг исключён из product acceptance.

Рассмотренные варианты:

1. оставить ScreenCaptureKit и добавить инструкцию по настройкам — отклонено,
   потому что инструкция невыполнима целевой аудиторией;
2. обходить TCC/MDM — запрещено платформой и политикой продукта;
3. использовать Core Audio Tap для system audio и отдельный input-контур для
   microphone.

Предлагаемое решение: проверить вариантом signed spike private/global Core
Audio Tap с исключением собственного процесса. System audio должен запрашивать
`NSAudioCaptureUsageDescription` штатным пользовательским prompt без захвата
экрана. Microphone захватывается отдельным AVFoundation/Core Audio контуром.

Состояние реализации 2026-07-28: внутренний candidate использует private Core
Audio Tap и отдельный AVAudioEngine microphone-контур; ScreenCaptureKit удалён
из capture path. Автоматические core/API/UI тесты проходят. Это не меняет
статус ADR: live signed TCC dual-source evidence на целевом corporate no-admin
Mac отсутствует.

Последствия: меняются lifecycle двух источников, permission/error state,
создание и cleanup tap/aggregate device, реакция на смену output device.
Стабильная Developer ID identity обязательна для проверки continuity между
обновлениями. Корпоративный MDM-запрет не обходится и должен давать отдельное
состояние `managed_denied`.

Проверка:

1. подписанный `.app` запускается на чистой no-admin учётной записи;
2. первый Start показывает отдельные system-audio и microphone prompts без
   admin credentials;
3. Screen Recording вручную не включается;
4. одновременно получен ненулевой PCM обоих источников;
5. Stop/Quit удаляют tap и aggregate device;
6. permission сохраняется после restart и обновления с той же identity;
7. проверены встроенный output, наушники, Teams/Zoom/browser и MDM denial;
8. 30-минутная сессия не оставляет виртуальные устройства.

Условие принятия: все критерии spike подтверждены evidence bundle на целевом
корпоративном Mac. После принятия ADR-009 получает статус `Superseded`.

## ADR-014. Микрофон в realtime выключен по умолчанию

Статус: Accepted

Контекст: состояние mute внутри Яндекс Телемоста, Zoom, Teams и браузерных ВКС
не имеет общего системного API. Факт, что процесс использует microphone device,
не означает, что собеседники слышат пользователя.

Решение: базовый realtime-сценарий захватывает только system audio. Микрофон
подключается отдельным явным переключателем перед Start. При выключенном
переключателе microphone permission не запрашивается, AVAudioEngine не
запускается, PCM pipe не создаётся, ASR-сессия не принимает microphone source.

Последствия: пользователь не попадает в транскрипцию по умолчанию. Если нужен
его голос, он вручную включает источник и самостоятельно согласует его с mute
в интерфейсе ВКС. Продукт не обещает автоматическую синхронизацию mute.

Проверка: unit/API/native contract tests подтверждают system-only default и
явный dual-source opt-in; packaged acceptance проверяет отсутствие microphone
prompt и microphone-сегментов в system-only сессии.

## Шаблон новой записи

```markdown
## ADR-XXX. Название

Статус: Proposed | Accepted | Rejected | Superseded

Контекст:

Рассмотренные варианты:

Решение:

Последствия:

Проверка:

Условие пересмотра:
```
