const form = document.querySelector("#form");
const partsList = document.querySelector("#parts-list");
const addPart = document.querySelector("#add-part");
const submit = document.querySelector("#submit");
const submitLabel = document.querySelector(".submit-label");
const statusBox = document.querySelector("#status");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const progressBar = document.querySelector("#progress-bar");
const progressPercent = document.querySelector("#progress-percent");
const progressTrack = document.querySelector("#progress-track");
const result = document.querySelector("#result");
const diarization = document.querySelector("#diarization");
const speakerCount = document.querySelector("#speaker-count");
const recoverGaps = document.querySelector("#recover-gaps");
const folderMessage = document.querySelector("#folder-message");
const modeButtons = document.querySelectorAll("[data-mode]");
const fileModePanel = document.querySelector("#file-mode-panel");
const liveModePanel = document.querySelector("#live-mode-panel");
const liveState = document.querySelector("#live-state");
const liveTimer = document.querySelector("#live-timer");
const liveStart = document.querySelector("#live-start");
const livePause = document.querySelector("#live-pause");
const liveStop = document.querySelector("#live-stop");
const liveNotice = document.querySelector("#live-notice");
const liveIncludeMicrophone = document.querySelector("#live-include-microphone");
const liveDiarization = document.querySelector("#live-diarization");
const liveHfToken = document.querySelector("#live-hf-token");
const liveSourceSummary = document.querySelector("#live-source-summary");
const systemAudioState = document.querySelector("#system-audio-state");
const microphoneState = document.querySelector("#microphone-state");
const liveTranscriptContent = document.querySelector("#live-transcript-content");
const liveDownloads = document.querySelector("#live-downloads");
const liveTxtLink = document.querySelector("#live-txt-link");
const liveJsonLink = document.querySelector("#live-json-link");
const liveDocxLink = document.querySelector("#live-docx-link");
const revealResult = document.querySelector("#reveal-result");
const liveRevealResult = document.querySelector("#live-reveal-result");
const liveRecovery = document.querySelector("#live-recovery");
const liveRecoveryMessage = document.querySelector("#live-recovery-message");
const liveRecoveryExport = document.querySelector("#live-recovery-export");
const maxRenderedRealtimeSegments = 200;
let realtimeSessionId = null;
let realtimeCursor = 0;
let realtimeRenderedSegments = 0;
let realtimeSegmentsRequestActive = false;
let recoverableRealtimeSessionId = null;

function selectMode(mode) {
  const liveMode = mode === "live";
  fileModePanel.classList.toggle("hidden", liveMode);
  liveModePanel.classList.toggle("hidden", !liveMode);
  fileModePanel.hidden = liveMode;
  liveModePanel.hidden = !liveMode;
  modeButtons.forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}

modeButtons.forEach((button, index) => {
  button.addEventListener("click", () => selectMode(button.dataset.mode));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? modeButtons.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + modeButtons.length)
          % modeButtons.length;
    const nextButton = modeButtons[nextIndex];
    selectMode(nextButton.dataset.mode);
    nextButton.focus();
  });
});

function formatDuration(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function setTextIfChanged(element, text) {
  if (element.textContent !== text) {
    element.textContent = text;
  }
}

const realtimeSourceLabels = {
  system: "Системный звук",
  microphone: "Микрофон",
};

function formatSegmentTime(totalSeconds) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  return formatDuration(seconds);
}

function createRealtimeSegment(segment, provisional = false) {
  const item = document.createElement("article");
  item.className = `live-segment${provisional ? " provisional" : ""}`;

  const meta = document.createElement("div");
  meta.className = "live-segment-meta";
  const source = segment.speaker || realtimeSourceLabels[segment.source] || "Аудио";
  meta.textContent = `${source} · ${formatSegmentTime(segment.start)}`;
  if (provisional) {
    const draft = document.createElement("span");
    draft.textContent = "Черновик";
    meta.append(" · ", draft);
  }

  const text = document.createElement("p");
  text.textContent = segment.text || "";
  item.append(meta, text);
  return item;
}

function showRealtimePlaceholder(message) {
  liveTranscriptContent.replaceChildren();
  const placeholder = document.createElement("div");
  placeholder.className = "live-placeholder";
  const text = document.createElement("p");
  text.id = "live-transcript-text";
  text.textContent = message;
  placeholder.append(text);
  liveTranscriptContent.append(placeholder);
}

function resetRealtimeTranscript(state) {
  realtimeSessionId = state.session_id || null;
  realtimeCursor = Math.max(
    0,
    Number(state.next_cursor || 0) - maxRenderedRealtimeSegments,
  );
  realtimeRenderedSegments = 0;
  const message = ["loading", "waiting_audio", "running"].includes(state.asr_status)
    ? "Слушаем встречу. Распознанная речь появится здесь с небольшой задержкой."
    : state.asr_status === "finalizing"
      ? "Завершаем распознавание и сохраняем результаты…"
      : "После запуска здесь будет появляться распознанная речь с небольшой задержкой.";
  showRealtimePlaceholder(message);
}

function appendRealtimeSegments(segments) {
  const committed = segments.filter(
    (segment) => segment && segment.committed !== false && segment.text,
  );
  if (!committed.length) return;
  const placeholder = liveTranscriptContent.querySelector(".live-placeholder");
  if (placeholder) placeholder.remove();
  committed.forEach((segment) => {
    liveTranscriptContent.append(createRealtimeSegment(segment));
    realtimeRenderedSegments += 1;
  });
  while (realtimeRenderedSegments > maxRenderedRealtimeSegments) {
    const first = liveTranscriptContent.querySelector(".live-segment");
    if (!first) break;
    first.remove();
    realtimeRenderedSegments -= 1;
  }
  liveTranscriptContent.scrollTop = liveTranscriptContent.scrollHeight;
}

async function refreshRealtimeSegments(state) {
  const sessionId = state.session_id || null;
  if (sessionId !== realtimeSessionId) resetRealtimeTranscript(state);
  const targetCursor = Number(state.next_cursor || 0);
  if (!sessionId || realtimeCursor >= targetCursor || realtimeSegmentsRequestActive) return;
  realtimeSegmentsRequestActive = true;
  try {
    do {
      const response = await fetch(
        `/api/realtime/segments?after=${realtimeCursor}&limit=${maxRenderedRealtimeSegments}`,
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось получить новые реплики.");
      if (sessionId !== realtimeSessionId) return;
      appendRealtimeSegments(Array.isArray(data.segments) ? data.segments : []);
      const nextCursor = Number(data.next_cursor);
      if (!Number.isFinite(nextCursor) || nextCursor <= realtimeCursor) break;
      realtimeCursor = nextCursor;
      if (!data.has_more) break;
    } while (realtimeCursor < targetCursor);
  } catch (error) {
    setTextIfChanged(liveNotice, `${error.message} Повторим автоматически.`);
  } finally {
    realtimeSegmentsRequestActive = false;
  }
}

function renderRealtimeDownloads(state) {
  const files = [
    [liveTxtLink, state.txt_name],
    [liveJsonLink, state.json_name],
    [liveDocxLink, state.docx_name],
  ];
  const ready = state.asr_status === "done" && files.every(([, name]) => Boolean(name));
  liveDownloads.classList.toggle("hidden", !ready);
  if (!ready) return;
  files.forEach(([link, name]) => {
    link.href = `/files/${encodeURIComponent(name)}`;
  });
  liveRevealResult.dataset.filename = state.docx_name;
}

function renderRealtime(state) {
  if ((state.session_id || null) !== realtimeSessionId) resetRealtimeTranscript(state);
  const captureActive = ["starting", "recording", "stopping"].includes(state.status);
  const asrActive = ["loading", "waiting_audio", "running", "finalizing"].includes(state.asr_status);
  const active = captureActive || asrActive;
  const stateLabel = {
    idle: "Готово к встрече",
    loading: "Загружаем модель",
    waiting_audio: "Ожидаем звук",
    running: "Идёт транскрибация",
    finalizing: "Сохраняем результат",
    done: "Готово",
    error: "Ошибка",
  }[state.asr_status] || {
    starting: "Запрашиваем доступ",
    recording: "Идёт транскрибация",
    stopping: "Завершаем",
    error: "Ошибка",
  }[state.status] || "Проверяем";
  const error = state.status === "error" || state.asr_status === "error";
  const microphoneEnabled = active
    ? Boolean(state.microphone_enabled)
    : liveIncludeMicrophone.checked;
  const diarizationEnabled = active
    ? Boolean(state.diarization_enabled)
    : liveDiarization.checked;
  setTextIfChanged(liveState, stateLabel);
  liveState.classList.toggle("planned", state.asr_status === "idle" && state.status === "idle");
  liveState.classList.toggle("recording", state.asr_status === "running");
  liveState.classList.toggle("error", error);
  liveModePanel.classList.toggle("is-recording", state.asr_status === "running");
  liveTimer.textContent = formatDuration(state.elapsed_seconds || 0);
  liveTimer.setAttribute("datetime", `PT${state.elapsed_seconds || 0}S`);
  const diarizationWarning = asrActive ? state.diarization_warning : null;
  setTextIfChanged(liveNotice, state.available
    ? (diarizationWarning || state.asr_message || state.message || "Готово к встрече.")
    : "Помощник захвата не собран. Перезапустите транскрибатор после обновления.");
  const waitingLabel = state.status === "starting"
    ? "проверяем"
    : state.status === "error"
      ? "ошибка"
      : "ожидаем";
  setTextIfChanged(systemAudioState, `Системный звук: ${state.system_audio ? "есть звук" : waitingLabel}`);
  setTextIfChanged(
    microphoneState,
    `Микрофон: ${microphoneEnabled ? (state.microphone ? "есть звук" : waitingLabel) : "выключен"}`,
  );
  setTextIfChanged(
    liveSourceSummary,
    `${microphoneEnabled ? "Системный звук + микрофон" : "Системный звук"}${diarizationEnabled ? " · спикеры включены" : ""}`,
  );
  systemAudioState.classList.toggle("active", Boolean(state.system_audio));
  microphoneState.classList.toggle("active", Boolean(state.microphone));
  liveIncludeMicrophone.disabled = active;
  liveDiarization.disabled = active;
  liveHfToken.disabled = active;
  liveStart.disabled = !state.available || active;
  livePause.disabled = true;
  liveStop.disabled = !active;
  renderRealtimeDownloads(state);
}

async function refreshRealtimeStatus() {
  try {
    const response = await fetch("/api/realtime/status");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось проверить захват.");
    renderRealtime(data);
    await refreshRealtimeSegments(data);
  } catch (error) {
    renderRealtime({
      status: "error",
      available: false,
      message: error.message,
      elapsed_seconds: 0,
      asr_status: "error",
      asr_message: error.message,
      session_id: realtimeSessionId,
      next_cursor: realtimeCursor,
    });
  }
}

async function refreshRealtimeRecovery() {
  try {
    const response = await fetch("/api/realtime/recovery");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось проверить восстановление.");
    const session = Array.isArray(data.sessions) ? data.sessions[0] : null;
    recoverableRealtimeSessionId = session?.session_id || null;
    liveRecovery.classList.toggle("hidden", !data.available || !session);
    if (data.available) {
      const count = Number(session?.segment_count || 0);
      liveRecoveryMessage.textContent = `Сохранено реплик: ${count}. Исходный realtime-звук не записывался.`;
    }
  } catch (_error) {
    liveRecovery.classList.add("hidden");
  }
}

liveRecoveryExport.addEventListener("click", async () => {
  liveRecoveryExport.disabled = true;
  liveRecoveryMessage.textContent = "Создаём TXT, DOCX и JSON из сохранённой встречи…";
  try {
    const response = await fetch("/api/realtime/recovery/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: recoverableRealtimeSessionId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось восстановить встречу.");
    renderRealtimeDownloads({ ...data, asr_status: "done" });
    liveRecovery.classList.add("hidden");
  } catch (error) {
    liveRecoveryMessage.textContent = error.message;
  } finally {
    liveRecoveryExport.disabled = false;
  }
});

liveStart.addEventListener("click", async () => {
  liveStart.disabled = true;
  liveNotice.textContent = "Запускаем встречу и загружаем модель…";
  try {
    const response = await fetch("/api/realtime/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        include_microphone: liveIncludeMicrophone.checked,
        diarization: liveDiarization.checked,
        hf_token: liveHfToken.value,
      }),
    });
    const data = await response.json();
    liveHfToken.value = "";
    if (!response.ok) throw new Error(data.error || "Не удалось начать встречу.");
    renderRealtime(data);
    await refreshRealtimeSegments(data);
  } catch (error) {
    liveNotice.textContent = error.message;
    liveState.textContent = "Ошибка";
    liveState.classList.add("error");
    liveStart.disabled = false;
  }
});

async function requestRealtimeStop() {
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/api/realtime/stop", {
        method: "POST",
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось завершить встречу.");
      return data;
    } catch (error) {
      lastError = error;
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError || new Error("Не удалось завершить встречу.");
}

liveStop.addEventListener("click", async () => {
  if (!window.confirm("Завершить встречу и сохранить транскрипцию?")) return;
  liveStop.disabled = true;
  setTextIfChanged(liveState, "Завершаем");
  setTextIfChanged(liveNotice, "Останавливаем захват и сохраняем встречу…");
  try {
    await requestRealtimeStop();
    setTextIfChanged(liveNotice, "Команда завершения принята. Сохраняем документы…");
    await refreshRealtimeStatus();
  } catch (error) {
    liveNotice.textContent = `${error.message} Текст встречи продолжает сохраняться локально.`;
    await refreshRealtimeStatus();
  }
});

refreshRealtimeStatus();
refreshRealtimeRecovery();
setInterval(refreshRealtimeStatus, 1500);

// Realtime-сессия принадлежит локальному backend, а не браузерной вкладке.
// После фонового режима браузер может задержать таймеры, поэтому при возврате
// сразу восстанавливаем фактическое состояние и прошедшее время с backend.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshRealtimeStatus();
});
window.addEventListener("focus", refreshRealtimeStatus);
window.addEventListener("pageshow", refreshRealtimeStatus);

const stageCaps = {
  uploading: 4,
  downloading_models: 16,
  preparing: 18,
  loading_model: 27,
  transcribing: 70,
  recovery: 84,
  diarization: 94,
  exporting: 99,
  done: 100,
};
let displayedProgress = 0;
let reportedProgress = 0;
let progressCap = 0;
let progressActive = false;
let formBusy = false;

function setSubmitLoading(loading) {
  formBusy = loading;
  submit.classList.toggle("loading", loading);
  submitLabel.textContent = loading ? "Транскрибируем…" : "Начать транскрибацию";
  submit.setAttribute("aria-busy", String(loading));
  submit.disabled = loading || selectedFiles().length === 0;
}

function renderProgress() {
  const rounded = Math.min(100, Math.round(displayedProgress));
  progressBar.style.width = `${rounded}%`;
  progressPercent.textContent = `${rounded}%`;
  progressTrack.setAttribute("aria-valuenow", String(rounded));
}

function resetProgress() {
  displayedProgress = 0;
  reportedProgress = 0;
  progressCap = stageCaps.uploading;
  progressActive = true;
  renderProgress();
}

function updateProgress(progress, stage) {
  reportedProgress = Math.max(reportedProgress, Number(progress) || 0);
  progressCap = Math.max(progressCap, stageCaps[stage] || reportedProgress);
  if (stage === "done") {
    displayedProgress = 100;
    progressActive = false;
    renderProgress();
  }
}

setInterval(() => {
  if (!progressActive) return;
  if (displayedProgress < reportedProgress) {
    displayedProgress = Math.min(
      reportedProgress,
      displayedProgress + Math.max(1, (reportedProgress - displayedProgress) * 0.25),
    );
  } else if (displayedProgress < progressCap) {
    displayedProgress = Math.min(
      progressCap,
      displayedProgress + Math.max(0.12, (progressCap - displayedProgress) * 0.025),
    );
  }
  renderProgress();
}, 1000);

diarization.addEventListener("change", () => {
  speakerCount.disabled = !diarization.checked;
  if (!diarization.checked) speakerCount.value = "";
});

function selectedFiles() {
  return [...partsList.querySelectorAll(".part-input")]
    .map((input) => input.files[0])
    .filter(Boolean);
}

function refreshParts() {
  const rows = [...partsList.querySelectorAll(".part-row")];
  rows.forEach((row, index) => {
    row.querySelector(".part-number").textContent = `Часть ${index + 1}`;
    const hasFile = row.querySelector(".dropzone").classList.contains("has-file");
    row.querySelector(".remove-part").classList.toggle(
      "hidden",
      rows.length === 1 && !hasFile,
    );
  });
  submit.disabled = formBusy || selectedFiles().length === 0;
}

function splitFilename(filename, maxBaseLength = 46) {
  const lastDot = filename.lastIndexOf(".");
  const extension = lastDot > 0 ? filename.slice(lastDot) : "";
  const base = lastDot > 0 ? filename.slice(0, lastDot) : filename;
  const baseCharacters = Array.from(base);
  if (baseCharacters.length <= maxBaseLength) {
    return { prefix: base, tail: extension };
  }
  const rightLength = Math.min(14, Math.max(8, Math.floor(maxBaseLength * 0.28)));
  const leftLength = Math.max(16, maxBaseLength - rightLength);
  return {
    prefix: baseCharacters.slice(0, leftLength).join(""),
    tail: `…${baseCharacters.slice(-rightLength).join("")}${extension}`,
  };
}

function renderFilename(title, filename) {
  const { prefix, tail } = splitFilename(filename);
  title.replaceChildren();
  title.title = filename;
  title.setAttribute("aria-label", filename);
  const prefixNode = document.createElement("span");
  prefixNode.className = "file-name-prefix";
  prefixNode.textContent = prefix;
  title.appendChild(prefixNode);
  if (tail) {
    const tailNode = document.createElement("span");
    tailNode.className = "file-name-tail";
    tailNode.textContent = tail;
    title.appendChild(tailNode);
  }
}

function selectFile(row, file) {
  if (!file) return;
  const input = row.querySelector(".part-input");
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  const dropzone = row.querySelector(".dropzone");
  const title = row.querySelector(".drop-title");
  dropzone.classList.add("has-file");
  dropzone.setAttribute("aria-label", `Выбран файл: ${file.name}`);
  renderFilename(title, file.name);
  row.querySelector(".drop-note").textContent = `${(file.size / 1024 / 1024).toFixed(1)} МБ`;
  row.querySelector(".file-hint").textContent = "Нажмите, чтобы заменить файл";
  result.classList.add("hidden");
  refreshParts();
}

function resetPart(row) {
  const input = row.querySelector(".part-input");
  const dropzone = row.querySelector(".dropzone");
  const title = row.querySelector(".drop-title");
  input.value = "";
  dropzone.classList.remove("has-file", "dragging");
  dropzone.removeAttribute("aria-label");
  title.removeAttribute("title");
  title.removeAttribute("aria-label");
  title.textContent = "Перетащите запись сюда";
  row.querySelector(".drop-note").textContent = "или нажмите, чтобы выбрать файл";
  row.querySelector(".file-hint").textContent = "WEBM, MP4, MP3, M4A и другие аудиоформаты";
}

function bindPart(row) {
  const input = row.querySelector(".part-input");
  const dropzone = row.querySelector(".dropzone");
  input.addEventListener("change", () => selectFile(row, input.files[0]));
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (event) => selectFile(row, event.dataTransfer.files[0]));
  row.querySelector(".remove-part").addEventListener("click", () => {
    if (partsList.querySelectorAll(".part-row").length === 1) {
      resetPart(row);
    } else {
      row.remove();
    }
    refreshParts();
  });
}

function createPart() {
  const row = document.createElement("div");
  row.className = "part-row";
  row.innerHTML = `
    <label class="dropzone">
      <input class="part-input" name="files" type="file" accept=".webm,.mp4,.wav,.mp3,.m4a,.flac,.ogg,.aac">
      <span class="part-number"></span>
      <span class="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15.5V20h14v-4.5"></path></svg>
      </span>
      <span class="file-card__info">
        <strong class="drop-title">Выберите следующую часть</strong>
        <span class="drop-note">или перетащите файл сюда</span>
        <small class="file-hint">Таймкоды продолжатся после предыдущей части</small>
      </span>
    </label>
    <button class="remove-part" type="button" aria-label="Удалить файл" title="Удалить файл">×</button>`;
  partsList.appendChild(row);
  bindPart(row);
  refreshParts();
  row.querySelector(".part-input").click();
}

partsList.querySelectorAll(".part-row").forEach(bindPart);
addPart.addEventListener("click", createPart);
refreshParts();

function showError(message) {
  progressActive = false;
  statusBox.classList.remove("hidden");
  statusBox.classList.add("error");
  statusTitle.textContent = "Не удалось обработать файл";
  statusMessage.textContent = message;
  setSubmitLoading(false);
}

async function poll(jobId) {
  const response = await fetch(`/api/status/${jobId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось получить статус.");
  setTextIfChanged(statusMessage, data.message);
  updateProgress(data.progress, data.stage);
  if (data.status === "done") {
    statusBox.classList.add("hidden");
    result.classList.remove("hidden");
    document.querySelector("#result-note").textContent = data.fallback
      ? "Готово. Часть обработки автоматически выполнена на CPU."
      : `Готово. Устройство: ${data.device.toUpperCase()}.`;
    document.querySelector("#txt-link").href = `/files/${encodeURIComponent(data.txt_name)}`;
    document.querySelector("#docx-link").href = `/files/${encodeURIComponent(data.docx_name)}`;
    document.querySelector("#json-link").href = `/files/${encodeURIComponent(data.json_name)}`;
    revealResult.dataset.filename = data.docx_name;
    setSubmitLoading(false);
    return;
  }
  if (data.status === "error") {
    showError(data.message);
    return;
  }
  setTimeout(() => poll(jobId).catch((error) => showError(error.message)), 1200);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = selectedFiles();
  if (!files.length) {
    showError("Добавьте хотя бы одну часть встречи.");
    return;
  }
  setSubmitLoading(true);
  resetProgress();
  result.classList.add("hidden");
  statusBox.classList.remove("hidden", "error");
  statusTitle.textContent = diarization.checked
    ? "Распознаём и разделяем спикеров"
    : "Обрабатываем запись";
  statusMessage.textContent = files.length > 1
    ? `Объединяем части встречи: ${files.length}.`
    : recoverGaps.checked
      ? "После распознавания дополнительно проверим пропущенные интервалы."
      : "Загружаем файл в локальный транскрибатор…";
  try {
    const response = await fetch("/api/transcribe", { method: "POST", body: new FormData(form) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось запустить обработку.");
    poll(data.id).catch((error) => showError(error.message));
  } catch (error) {
    showError(error.message);
  }
});

document.querySelectorAll("[data-open-folder]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    folderMessage.classList.add("hidden");
    try {
      const response = await fetch(`/api/open-folder/${button.dataset.openFolder}`, {
        method: "POST",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось открыть папку.");
      folderMessage.textContent = data.message;
      folderMessage.classList.remove("hidden", "error");
    } catch (error) {
      folderMessage.textContent = error.message;
      folderMessage.classList.remove("hidden");
      folderMessage.classList.add("error");
    } finally {
      button.disabled = false;
    }
  });
});

async function showResultInFinder(button) {
  const filename = button.dataset.filename;
  if (!filename) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/reveal-file/${encodeURIComponent(filename)}`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось показать результат.");
  } catch (error) {
    folderMessage.textContent = error.message;
    folderMessage.classList.remove("hidden");
    folderMessage.classList.add("error");
  } finally {
    button.disabled = false;
  }
}

[revealResult, liveRevealResult].forEach((button) => {
  button.addEventListener("click", () => showResultInFinder(button));
});
