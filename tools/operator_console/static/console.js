"use strict";

// This shell does not replace any map, color, interpolation or drawing function.
const sessionId = crypto.randomUUID();
let consoleSnapshot = null;
let configuredFingerprint = null;
let actionPending = false;
let pollPending = false;
let consoleStarted = false;
let positionedCount = 0;
let positionedMission = null;

// Mission totals come from the acquisition pipeline. The renderer keeps only
// the latest 5,000 path points; its buffer length is not a mission total.
function acceptPositionedCount(mission, value) {
  if (mission && state.missionId && mission !== state.missionId) return;
  if (mission && mission !== positionedMission) {
    positionedMission = mission;
    positionedCount = 0;
  }
  const count = Number(value);
  if (Number.isFinite(count) && count >= 0) positionedCount = Math.max(positionedCount, Math.floor(count));
  $("sample-count").textContent = String(positionedCount);
}

// Units and telemetry only: the original map geometry, gradient and numeric
// color transform stay untouched. Real bins are CPS, not FS-5000 dose units.
const originalReferenceLabel = regulatoryBandForExcessRate;
const originalEnvelope = handleEnvelope;
const originalReadings = updateReadings;
const countsMap = () => consoleSnapshot?.inputs.radiation === "real";
formatRateWithUnit = function (value) {
  if (countsMap()) return `${formatNumber(value, 2)} CPS`;
  const scaled = scaledDoseRate(value);
  return Number.isFinite(scaled.value) ? `${formatNumber(scaled.value, 2)} ${scaled.unit}` : "—";
};
formatDoseRate = function (value) {return formatNumber(scaledDoseRate(value).value, 2);};
formatAxisValue = function (value) {return formatNumber(value, 2);};
regulatoryBandForExcessRate = function (value) {
  return countsMap() ? "Contagens · sem conversão CPS para dose" : originalReferenceLabel(value);
};
updateReadings = function () {
  originalReadings();
  $("dose-total").textContent = formatNumber(scaledDose(state.accumulatedDose).value, 2);
  if (countsMap() && state.radiation?.dose_rate_uSv_h == null) {
    $("dose-rate").textContent = "—";
    $("dose-rate-unit").textContent = "µSv/h";
  }
  acceptPositionedCount(state.missionId, state.map?.sample_count);
};
handleEnvelope = function (envelope) {
  const payload = envelope.payload || {};
  if (state.missionId && payload.mission_id && payload.mission_id !== state.missionId) return;
  const before = state.accumulatedDose;
  originalEnvelope(envelope);
  if (countsMap() && envelope.type === "mapped_sample") {
    state.accumulatedDose = before;
    updateReadings();
  }
  if (envelope.type === "mapped_sample") acceptPositionedCount(payload.mission_id, payload.mapped_sequence);
  if (envelope.type === "mission_state") acceptPositionedCount(payload.mission_id, payload.counts?.mapped);
  if (envelope.type === "map_update") acceptPositionedCount(payload.mission_id, payload.sample_count);
};

async function consoleApi(path, body) {
  const response = await fetch(`/api/console${path}`, {
    cache: "no-store", headers: {"Content-Type": "application/json"},
    ...(body === undefined ? {} : {method: "POST", body: JSON.stringify(body)}),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Falha HTTP ${response.status}`);
  }
  return response.json();
}

function readSetup() {
  return {
    mode: $("operation-mode").value,
    x_m: numberFromInput("source-x"), y_m: numberFromInput("source-y"),
    dose_rate_at_1m_uSv_h: numberFromInput("source-strength") * 1000,
    duration_s: Number($("mission-duration").value),
  };
}

function modeDescription(mode) {
  return {
    simulation: "Fonte, detector e robô simulados. Nenhum equipamento é acessado.",
    usb_simulated_robot: "Radiacode no USB deste computador. O movimento e as posições são virtuais.",
    robot_simulated_source: "Go2 pelo Wi-Fi. As leituras são sintéticas, calculadas na posição real do robô.",
    hardware: "Go2 pelo Wi-Fi e Radiacode pelo USB. Aquisição e posição independentes, sincronizadas por timestamp.",
  }[mode];
}

function showModeChoice() {
  const mode = $("operation-mode").value;
  const synthetic = mode === "simulation" || mode === "robot_simulated_source";
  $("source-details").hidden = !synthetic;
  $("input-explanation").textContent = modeDescription(mode);
  $("operation-mode").title = modeDescription(mode);
}

function elapsedLabel(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60]
    .map(part => String(part).padStart(2, "0")).join(":");
}

function setupNumber(value) {
  if (value === "") return value;
  const number = Number(value);
  // Show two decimals where exact; retain finer operator-entered settings.
  return Number.isFinite(number) && number === Number(number.toFixed(2))
    ? number.toFixed(2) : String(value);
}

function paintConsole(snapshot) {
  consoleSnapshot = snapshot;
  const status = snapshot.status;
  const running = status.state === "RUNNING" || status.state === "STOPPING";
  const realRobot = snapshot.inputs.robot === "real";
  const realRadiation = snapshot.inputs.radiation === "real";
  if (!actionPending) {
    $("operation-mode").value = snapshot.mode;
    showModeChoice();
  }
  $("operation-mode").classList.toggle("physical", realRobot || realRadiation);
  for (const [part, connected, label] of [
    ["robot", snapshot.robot.conectado, realRobot ? "Go2 real" : "Simulado"],
    ["detector", snapshot.radiation.conectado, realRadiation ? "Radiacode USB" : "Simulada"],
  ]) {
    $(part + "-status").textContent = `${label} · ${connected ? "online" : "aguardando"}`;
    $(part + "-light").classList.toggle("ok", !!connected);
    $(part + "-light").classList.toggle("bad", !connected);
  }
  $("mission-status").textContent = {READY: "Pronto", RUNNING: "Em andamento", STOPPING: "Salvando", COMPLETED: "Encerrada", FAULT: "Falha"}[status.state] || status.state;
  $("mission-status").classList.toggle("recording", running);
  $("reading-age").textContent = snapshot.reading_age_s == null ? "—" : `${formatNumber(snapshot.reading_age_s, 2)} s`;
  $("record-light").classList.toggle("recording", running);
  $("record-label").textContent = running ? "Registrando" : (status.mission_id ? "Registro salvo" : "Aguardando início");
  $("mission-lock").textContent = running ? "· Entradas bloqueadas durante a missão" : "· Entradas editáveis";
  $("operation-mode").disabled = running || actionPending;
  $("configure-button").disabled = running || actionPending;
  for (const id of ["source-x", "source-y", "source-strength", "mission-duration", "apply-mode", "apply-source"]) $(id).disabled = running || actionPending;
  for (const id of ["source-x", "source-y", "source-strength"]) {
    const input = $(id);
    if (document.activeElement !== input) input.value = setupNumber(input.value);
  }
  $("start-button").disabled = running || actionPending || !snapshot.robot.conectado || !snapshot.radiation.conectado || (realRadiation && (snapshot.reading_age_s == null || snapshot.reading_age_s > 3));
  $("start-button").textContent = running ? "Mapeamento em andamento" : "Iniciar mapeamento";
  $("finish-button").disabled = !running || actionPending;
  $("enable-control").disabled = !running || snapshot.control_enabled || actionPending;
  $("enable-control").textContent = "Habilitar teclado";
  $("enable-control").hidden = snapshot.control_enabled;
  $("keyboard-control").hidden = !running;
  $("physical-ack-row").hidden = !realRobot || snapshot.control_enabled;
  $("control-state").textContent = snapshot.control_enabled ? "Setas do teclado · solte para parar · Esc interrompe." : "Teclado bloqueado. Habilite para movimentar.";
  const r = status.radiation;
  $("cps-reading").textContent = r?.cps == null ? "—" : formatNumber(r.cps, 2);
  $("cpm-reading").textContent = r?.cpm == null ? "—" : formatNumber(r.cpm, 2);
  if (realRadiation && (snapshot.reading_age_s == null || snapshot.reading_age_s > 3)) $("dose-rate").textContent = "—";
  $("data-origin").textContent = realRadiation ? "USB real · dose provisória · CPM = 60 × CPS" : "Radiação simulada · treinamento";
  $("spatial-note").textContent = realRobot
    ? (realRadiation ? "Posição em odometria local. Offset e latência devem ser conferidos no ensaio real." : "Robô real com radiação sintética. Este modo testa comunicação, movimento e sincronização.")
    : (realRadiation ? "Posição simulada: este mapa testa o software e não representa a distribuição física da radiação." : "Ambiente de treinamento com fonte e posição virtuais.");
  $("frame-label").textContent = snapshot.mode === "simulation" ? "Mundo simulado" : "Odometria local (odom)";
  $("map-title").textContent = realRadiation ? "Mapa de contagens pelas medições" : "Mapa construído pelas medições";
  document.querySelector(".public-reference").textContent = realRadiation ? "Cores: contagens relativas · escala em CPS" : "Cores: intensidade relativa · referências CNEN no cursor";
  $("mission-id").textContent = status.mission_id || "—";
  $("duration-reading").textContent = `${snapshot.setup.duration_s / 60} minutos`;
  $("elapsed").textContent = elapsedLabel(status.simulation_time_ns / 1e9);
  $("pose-reading").textContent = status.pose ? `${formatNumber(status.pose.x_m, 2)} / ${formatNumber(status.pose.y_m, 2)} m` : "—";
  $("download-button").setAttribute("aria-disabled", String(!status.mission_id || running));
  const errors = [snapshot.robot.erro, snapshot.radiation.erro, snapshot.teleop_error].filter(Boolean);
  $("diagnostic-text").textContent = errors.length ? errors.join(" · ") : "Nenhuma falha reportada.";
  $("clock").textContent = new Date().toLocaleTimeString("pt-BR", {hour12: false});
  // Polls report connectivity and pose; only the original map events provide
  // the dose anchor. An older HTTP snapshot must not roll the dose backward.
  const {exposure, ...telemetryStatus} = status;
  updateStatus(telemetryStatus);
  acceptPositionedCount(status.mission_id, status.counts?.mapped);
}

async function reloadScenario() {
  state.scenario = await api("/scenario");
  state.configuredSource = initialSourceFromScenario();
  state.pose = null; state.displayPose = null; state.viewBox = null;
  state.mapped = []; state.map = null; state.radiation = null;
  state.missionId = null; state.accumulatedDose = 0;
  positionedMission = null; positionedCount = 0;
  state.pressedKeys.clear(); state.lastCommand = null;
  acceptPose(fallbackPose(), true);
  updateReadings(); scheduleRender();
}

async function applyInputs(setup = readSetup()) {
  const result = await consoleApi("/configure", setup);
  configuredFingerprint = JSON.stringify(setup);
  $("physical-ack").checked = false;
  await reloadScenario();
  paintConsole(result);
  setMessage(result.message);
}

async function perform(action) {
  if (actionPending) return;
  actionPending = true;
  if (consoleSnapshot) paintConsole(consoleSnapshot);
  try {await action();}
  catch (error) {
    setMessage(error.message, true);
    if ($("config-dialog").open) {
      $("config-message").textContent = error.message;
      $("config-message").hidden = false;
    }
  }
  finally {
    actionPending = false;
    await pollConsole();
  }
}

startSimulation = async function () {
  await perform(async () => {
    if (configuredFingerprint !== JSON.stringify(readSetup())) await applyInputs();
    await consoleApi("/start", {});
    state.scenario = await api("/scenario");
    state.configuredSource = initialSourceFromScenario();
    state.mapped = []; state.map = null; state.accumulatedDose = 0;
    positionedMission = null; positionedCount = 0;
    state.viewBox = null; state.pressedKeys.clear();
    paintConsole(await consoleApi("/state"));
    if (consoleSnapshot.inputs.robot === "simulated") {
      await consoleApi("/enable-control", {client: sessionId});
      paintConsole(await consoleApi("/state"));
    }
    setMessage("Missão iniciada. As entradas ficam bloqueadas até encerrar e salvar.");
  });
};

sendCurrentCommand = async function (force = false) {
  if (!consoleSnapshot?.control_enabled || state.missionState !== "RUNNING") return;
  const command = currentCommand();
  const signature = `${command.linear_m_s}:${command.yaw_rate_rad_s}`;
  if (!force && signature === state.lastCommand) return;
  state.lastCommand = signature;
  try {await consoleApi("/control", {...command, client: sessionId});}
  catch (error) {state.lastCommand = null; setMessage(`Controle: ${error.message}`, true);}
};

async function brake() {
  state.pressedKeys.clear(); state.lastCommand = null;
  if (!consoleSnapshot?.control_enabled) return;
  await consoleApi("/brake", {});
  await pollConsole();
  setMessage("Parada solicitada e controle bloqueado. Habilite o controle para voltar a mover.");
}

// Existing keyup sends zero. Losing browser focus also revokes the motion enable.
window.addEventListener("blur", () => void brake().catch(() => {}));
window.addEventListener("pagehide", () => {
  navigator.sendBeacon("/api/console/brake", new Blob(["{}"], {type: "application/json"}));
});
document.addEventListener("visibilitychange", () => {if (document.hidden) void brake().catch(() => {});});
window.addEventListener("keydown", event => {
  if (event.key === "Escape") void brake().catch(() => {});
});

function fillSetup(setup) {
  $("operation-mode").value = setup.mode;
  $("source-x").value = setupNumber(setup.x_m);
  $("source-y").value = setupNumber(setup.y_m);
  $("source-strength").value = setupNumber(setup.dose_rate_at_1m_uSv_h / 1000);
  $("mission-duration").value = String(setup.duration_s);
  showModeChoice();
}
$("configure-button").addEventListener("click", () => {
  if (consoleSnapshot) $("mission-duration").value = String(consoleSnapshot.setup.duration_s);
  $("config-message").hidden = true;
  $("config-dialog").showModal();
});
$("close-config").addEventListener("click", () => {
  if (consoleSnapshot) $("mission-duration").value = String(consoleSnapshot.setup.duration_s);
  $("config-dialog").close();
});
$("config-dialog").addEventListener("close", () => {
  if (consoleSnapshot) $("mission-duration").value = String(consoleSnapshot.setup.duration_s);
});
$("apply-mode").addEventListener("click", () => void perform(async () => {
  await applyInputs();
  $("config-dialog").close();
}));
$("expand-map").addEventListener("click", () => {
  const expanded = document.body.classList.toggle("map-focus");
  $("expand-map").setAttribute("aria-pressed", String(expanded));
  $("expand-map-label").textContent = expanded ? "Restaurar painel" : "Ampliar mapa";
  scheduleRender();
});
$("operation-mode").addEventListener("change", () => {
  const setup = readSetup();
  void perform(() => applyInputs(setup));
});
$("apply-source").addEventListener("click", () => void perform(() => applyInputs()));
$("finish-button").addEventListener("click", () => void perform(async () => {
  state.pressedKeys.clear(); state.lastCommand = null;
  await consoleApi("/stop", {});
  setMessage("Missão encerrada e salva. Você pode baixar os dados ou trocar as entradas.");
}));
$("enable-control").addEventListener("click", () => void perform(async () => {
  await consoleApi("/enable-control", {client: sessionId, acknowledge_physical_robot: $("physical-ack").checked});
  setMessage("Controle habilitado. Solte as setas para parar.");
}));
$("global-brake-button").addEventListener("click", () => {
  state.pressedKeys.clear(); state.lastCommand = null;
  void consoleApi("/brake", {}).then(() => {
    setMessage("Parada solicitada e controle bloqueado.");
    return pollConsole();
  }).catch(error => setMessage(`Parada: ${error.message}`, true));
});
$("download-button").addEventListener("click", event => {
  if ($("download-button").getAttribute("aria-disabled") === "true") event.preventDefault();
});

async function pollConsole() {
  if (pollPending) return;
  pollPending = true;
  try {
    const value = await consoleApi("/state");
    if (!consoleStarted) {
      consoleStarted = true;
      fillSetup(value.setup);
      configuredFingerprint = JSON.stringify(value.setup);
      showModeChoice();
    }
    paintConsole(value);
  } catch (error) {$("diagnostic-text").textContent = `Console indisponível: ${error.message}`;}
  finally {pollPending = false;}
}
setInterval(() => void pollConsole(), 1000);
void pollConsole();
