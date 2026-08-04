# Product readiness health-check

Статус: internal candidate, внешний release `NO-GO`
Дата проверки: 2026-08-04
Source state: `codex/product-app-release`; точный immutable commit будет записан
в manifest финального DMG
Целевая версия: product `.app` 0.2.x

## Verdict

Source/runtime internal candidate достигнут. Файловая offline-транскрибация,
runtime identity, release audits и внутренний realtime-контур подтверждены
ниже. Candidate подписан ad hoc и не должен передаваться коллегам как готовый
продукт.

Внешний verdict остаётся `NO-GO`: отсутствуют Developer ID identity/key,
notarization, stapling, Gatekeeper и clean corporate no-admin/MDM/TCC
acceptance. Наличие кода, unit tests и ad-hoc `.app` эти P0 не закрывает.

## Подтверждённое evidence

| Gate | Результат |
| --- | --- |
| Automated suite | PASS, 83/83 |
| Frozen runtime identity | PASS: `/api/health` возвращает точные `build_id` и `instance_id` |
| Offline bundled GigaAM file ASR | PASS |
| Realtime core/API/UI/export | IMPLEMENTED, automated tests PASS |
| Realtime anonymous speaker diarization | IMPLEMENTED, real-meeting quality benchmark pending |
| Live signed system+mic TCC | UNKNOWN |
| Mach-O compatibility audit | PASS: 417 Mach-O, arm64, minOS <= 15 |
| Product FFmpeg | PASS: LGPL, network disabled, required filters/muxer/protocols |
| Python license audit | PASS: 41 included packages mapped |
| Candidate signing | ad hoc only |
| Final DMG release guard | IMPLEMENTED: requires Developer ID + notary profile, signs and assesses app/DMG |
| Final signed DMG execution | BLOCKED: Apple identity/profile absent on build Mac |

Offline file-ASR smoke выполнялся с `HF_HUB_OFFLINE=1`, explicit bundled GigaAM
model directory и без token. Десятисекундный WAV завершился `status=done`:

- TXT 284 B, JSON 2.1 KiB, DOCX 38 KiB;
- 1 сегмент, 136 символов;
- `processing.mode=local_windows`;
- `device=cpu`.

Базовый файловый режим использует bundled GigaAM offline и не требует pyannote
models, HF token или сети. Pyannote-модели не входят в bundle: diarization
остаётся optional gated path, где пользователь отдельно принимает условия и
временно вводит Read token.

## Realtime boundary

Internal candidate содержит Core Audio Tap для system audio, отдельный
AVAudioEngine microphone-контур, bounded PCM buffers, window scheduler,
локальный GigaAM adapter, overlap dedup, API/UI state и TXT/JSON/DOCX export.
Исходный realtime PCM не должен записываться на диск.

Опциональная realtime-diarization использует word timestamps GigaAM,
exclusive speaker turns и embeddings pyannote Community-1. Она акустически
разделяет системный звук на анонимные `Спикер N` без интеграции с ВКС и не
изменяет аудиовход ASR. Unit и service/export contracts подтверждены; реальная
точность labels, перебивания и дополнительная latency ещё требуют acceptance.

Это не является realtime product acceptance. [ADR-013](11_ARCHITECTURE_DECISIONS.md)
остаётся `Proposed`, пока на целевом подписанном `.app` не подтверждены:

1. отдельные system-audio и microphone prompts без admin credentials;
2. отсутствие ручного Screen Recording step;
3. одновременный ненулевой PCM обоих источников;
4. cleanup tap/aggregate device после Stop/Quit и 30-минутной сессии;
5. permission continuity после restart/update с той же Developer ID identity;
6. built-in output, наушники, Teams/Zoom/browser и реальный MDM denial.
7. устойчивые `Спикер N` на контрольной встрече с 2–6 участниками, сменой
   очередности и короткими перебиваниями.

## External P0

1. Получить и назначить release owner для `Developer ID Application` identity
   и private key.
2. Подписать все nested Mach-O bottom-up и внешний `.app` стабильной identity.
3. Выполнить notarization, stapling и Gatekeeper assessment.
4. Запустить подготовленный fail-closed product DMG pipeline и проверить
   установку в `~/Applications` без admin.
5. Выполнить L5 на чистой corporate no-admin учётной записи: install,
   system-audio/microphone prompts, MDM/TCC states, bundled offline file ASR,
   realtime dual-source, Stop/Quit/restart/update.
6. Повторить Mach-O, FFmpeg, license, signature, network/token/log и checksum
   audits на точном final signed artifact.

MDM/PPPC-запрет не обходится кодом. Если корпоративная политика запрещает
audio capture, решение принимает владелец IT-профиля.

## Что нельзя называть готовым

- transferable/notarized product release;
- Gatekeeper acceptance;
- no-admin first-run на корпоративном Mac;
- live signed dual-source realtime capture;
- continuity TCC-разрешений между обновлениями;
- MDM denial/error acceptance;
- 30-минутная realtime-сессия;
- final signed DMG и rollback acceptance.

UI scope не расширяется. Realtime нельзя рекламировать как готовую
пользовательскую функцию до закрытия перечисленных evidence gates.
