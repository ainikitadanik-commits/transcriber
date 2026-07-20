const form = document.querySelector("#form");
const partsList = document.querySelector("#parts-list");
const addPart = document.querySelector("#add-part");
const submit = document.querySelector("#submit");
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

function selectMode(mode) {
  const liveMode = mode === "live";
  fileModePanel.classList.toggle("hidden", liveMode);
  liveModePanel.classList.toggle("hidden", !liveMode);
  modeButtons.forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

modeButtons.forEach((button) => {
  button.addEventListener("click", () => selectMode(button.dataset.mode));
});

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
    row.querySelector(".remove-part").classList.toggle("hidden", rows.length === 1);
  });
  submit.disabled = selectedFiles().length === 0;
}

function selectFile(row, file) {
  if (!file) return;
  const input = row.querySelector(".part-input");
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  row.querySelector(".dropzone").classList.add("has-file");
  row.querySelector(".drop-title").textContent = file.name;
  row.querySelector(".drop-note").textContent = `${(file.size / 1024 / 1024).toFixed(1)} МБ`;
  result.classList.add("hidden");
  refreshParts();
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
    row.remove();
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
      <span class="upload-icon" aria-hidden="true">↑</span>
      <strong class="drop-title">Выберите следующую часть</strong>
      <span class="drop-note">или перетащите файл сюда</span>
      <small>Таймкоды продолжатся после предыдущей части</small>
    </label>
    <button class="remove-part" type="button" aria-label="Удалить часть">×</button>`;
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
  submit.disabled = false;
}

async function poll(jobId) {
  const response = await fetch(`/api/status/${jobId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось получить статус.");
  statusMessage.textContent = data.message;
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
    submit.disabled = false;
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
  submit.disabled = true;
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
