# UI polish specification

Статус: нормативная спецификация визуального слоя
Актуально на: 2026-07-20

## Intent

Привести файловый сценарий и realtime capture diagnostic к единой светлой
premium glassmorphism-системе, сохранив текущую бизнес-логику, form fields,
API и локальную модель данных.

UI не является доказательством готовности backend-функции. Нереализованные
Pause, live ASR, provisional/committed text и realtime export не имитируются.

## Scope

Разрешено менять:

- `src/transcriber/web/templates/index.html`;
- `src/transcriber/web/static/app.css`;
- presentation/state helpers в `src/transcriber/web/static/app.js`;
- UI regression tests;
- связанную каноническую документацию.

Не разрешено этой задачей менять:

- Flask endpoints и IPC;
- pipeline, модели, FFmpeg и output contracts;
- capture implementation;
- пути пользовательских данных;
- realtime state machine и JSON schema.

## Design system

Design tokens определяются в `:root`, а не размазываются случайными значениями:

- фон `#F7FAF8`;
- белые полупрозрачные surfaces;
- основной текст `#13231E`;
- вторичный текст `#6B7975`;
- primary `#14795F`;
- mint/cyan/blue/violet используются точечно;
- CTA gradient: mint → cyan → blue → violet;
- радиусы: 30 / 20 / 16 / 14 px и pill;
- тени только мягкие зелёно-серые;
- transition 160 ms;
- внешний web-font/CDN запрещён.

Brand title использует локальный serif fallback. Иконки — единый локальный
outline SVG-набор.

## Layout contract

- основной контент центрирован и не шире 900 px;
- общий header, glass shell, mode tabs, local files panel и privacy footer;
- файловый и realtime-разделы используют одну визуальную систему;
- `min-width: 0` проходит через все flex/grid containers;
- ни один viewport не имеет горизонтальной прокрутки;
- контрольные ширины: 1440, 1280, 1024, 820, 640 и 480 px.

На ширине до 640 px настройки, realtime actions и local files panel становятся
одноколоночными, кнопки остаются полностью видимыми.

## Filename contract

Исходное имя `File.name` и FormData не меняются.

Presentation:

- basename и extension выводятся раздельно;
- длинный basename сокращается визуально в середине;
- extension всегда видим;
- полное имя доступно через `title` и `aria-label`;
- карточка не шире родителя;
- remove action не перекрывает имя;
- поддерживаются 150+ символов, несколько точек, отсутствие расширения,
  кириллица и Unicode.

Глобальный `overflow-x: hidden` не считается достаточным исправлением без
корректных grid/flex constraints.

## Accessibility contract

- tabs имеют `role=tab`, roving tabindex и Arrow Left/Right/Home/End;
- кнопки остаются `<button>`;
- поля имеют labels;
- focus-visible не удаляется;
- upload control показывает focus на dropzone;
- realtime status и ошибки используют live regions;
- состояние не передаётся только цветом;
- decorative SVG имеют `aria-hidden=true`;
- reduced-motion отключает постоянные анимации.

## Realtime truthfulness

Текущий экран называется «Захват звука встречи» или явно маркируется как
capture diagnostic.

Допустимо показывать:

- helper availability;
- system audio/microphone status;
- timer;
- Start/Stop capture;
- permission/capture error.

Обязательно:

- Start не называется готовой realtime-транскрибацией;
- Pause остаётся disabled и помечается «Планируется»;
- live transcript panel помечается как будущая функция;
- Stop не обещает TXT/JSON/DOCX.

## Acceptance

1. Два режима визуально образуют одну систему.
2. File upload/settings/progress/result/Finder actions сохраняют текущие
   контракты.
3. 150+ filename не создаёт overflow, extension и full accessible name
   сохранены.
4. Keyboard tabs, form controls, accordion и actions имеют видимый focus.
5. На 1440/1280/1024/820/640/480 нет горизонтального scroll.
6. Loading/error/disabled states оформлены.
7. Realtime не выдаёт planned за current.
8. Нет новых внешних запросов, console errors или frontend dependencies.
9. `node --check` и полный Python suite проходят.
10. Сохранены итоговые screenshots обоих режимов.

TypeScript и отдельный frontend linter в текущем vanilla frontend отсутствуют;
они указываются как `N/A`, а не как пройденные проверки.

## Verification record

Проверено 2026-07-20 на dev runtime из текущего source tree:

- 1440 / 1280 / 1024 / 820 / 640 / 480 px:
  `scrollWidth === clientWidth`;
- keyboard Arrow Left переключает `Рилтайм` → `Из файла` и переносит focus;
- Pause остаётся disabled, live text явно помечен `планируется`;
- browser console: ошибок и предупреждений нет;
- `node --check`: PASS;
- Python suite: 38/38 PASS;
- screenshots: `output/playwright/ui-file-1440.png` и
  `output/playwright/ui-realtime-1440.png`.

Проверка длинных имён включает 150+ символов, несколько точек, отсутствие
расширения, кириллицу и Unicode. Разбиение выполняется по Unicode code points,
extension остаётся отдельным несжимаемым хвостом, а исходный `File` не меняется.

Установленный `~/Applications/Транскрибатор.app` пока содержит предыдущие
web-assets. На этапе финальной упаковки обязательны полная пересборка
`REBUILD_RUNTIME=1 scripts/build_app_bundle.sh` и замена приложения целиком;
копирование отдельных ресурсов внутрь подписанного bundle запрещено.
