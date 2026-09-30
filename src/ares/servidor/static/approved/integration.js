"use strict";

// Presentation adapter only. Position synchronization, USB ownership and
// persistence remain in the existing backend; timestamps are never rewritten.
const integration = {snapshot: null, telemetry: null, commands: null, generation: 0,
  stopped: false, sampleCount: 0, sampleKeys: new Set(), savedMission: null, pending: false};

async function backend(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    cache: "no-store", headers: {"Content-Type": "application/json"}, ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

function poseForDisplay(pose) {
  if (!pose || ![pose.x, pose.y, pose.yaw, pose.ts].every(Number.isFinite)) return null;
  return {x_m: pose.x, y_m: pose.y, z_m: 0.32, yaw_rad: pose.yaw, ts: pose.ts};
}

function appendSample(sample) {
  if (!sample || ![sample.ts, sample.x, sample.y, sample.cps].every(Number.isFinite)) return;
  const key = JSON.stringify([sample.ts, sample.x, sample.y, sample.cps]);
  if (integration.sampleKeys.has(key)) return false;
  integration.sampleKeys.add(key);
  state.mapped.push({...sample, sensor_x_m: sample.x, sensor_y_m: sample.y,
    // Legacy renderer field contains CPS only; color scale explicitly says CPS.
    dose_rate_uSv_h_filtered: sample.cps, displayKey: key});
  if (state.mapped.length > 5000) integration.sampleKeys.delete(state.mapped.shift().displayKey);
  scheduleRender();
  return true;
}

function showExports(id) {
  if (!id) return;
  integration.savedMission = id;
  for (const [name, suffix] of [["csv", "/amostras.csv"], ["json", ".json"]]) {
    const link = $(`export-${name}`);
    link.href = `/api/missoes/${encodeURIComponent(id)}${suffix}`;
    link.hidden = false;
  }
}

async function recoverHistory(id, generation) {
  try {
    const saved = await backend(`/missoes/${encodeURIComponent(id)}.json`);
    if (generation !== integration.generation || state.missionId !== id) return;
    const live = state.mapped.slice();
    integration.sampleCount = Math.max(integration.sampleCount, (saved.amostras || []).length);
    state.mapped = [];
    integration.sampleKeys.clear();
    for (const sample of (saved.amostras || []).slice(-5000)) appendSample(sample);
    for (const sample of live) appendSample(sample);
    state.mapped.sort((a, b) => a.ts - b.ts);
    scheduleRender();
  } catch (error) {
    setMessage(`Histórico indisponível: ${error.message}`, true);
  }
}

function applySnapshot(snapshot, recover = false) {
  integration.snapshot = snapshot;
  const id = snapshot.missao?.id ?? null;
  if (id !== state.missionId) {
    if (id != null) {
      state.mapped = [];
      integration.sampleKeys.clear();
      state.viewBox = null;
      integration.sampleCount = snapshot.missao?.n_amostras ?? 0;
    }
    state.missionId = id;
    integration.generation += 1;
    stopRobot();
    if (id != null) void recoverHistory(id, integration.generation);
  } else if (recover && id != null) {
    void recoverHistory(id, integration.generation);
  }
  state.missionState = id != null ? "RUNNING" : "READY";
  if (snapshot.robo?.conectado && snapshot.pose) {
    const pose = poseForDisplay(snapshot.pose);
    if (pose) acceptPose(pose);
  } else if (!snapshot.robo?.conectado) {
    state.pose = null;
    state.displayPose = null;
    stopRobot();
  }
  if (Object.hasOwn(snapshot, "leitura")) state.radiation = snapshot.leitura;
  if (!snapshot.radiacao?.conectado) state.radiation = null;
  if (id != null) showExports(id);
  $("integration-mode").textContent = snapshot.modo === "real"
    ? "Radiação real · posição Go2/WebRTC" : "Radiação real · posição simulada";
  $("device-status").textContent = `Detector: ${snapshot.radiacao?.conectado ? "conectado" : "aguardando USB"} · Go2: ${snapshot.robo?.conectado ? "conectado" : "aguardando conexão"}`;
  const ready = !!(snapshot.robo?.conectado && snapshot.radiacao?.conectado && snapshot.pose);
  $("start-button").disabled = integration.pending || id != null || !ready;
  $("end-button").disabled = integration.pending || id == null;
  $("map-mode").textContent = snapshot.modo === "real" ? "Posição do Go2" : "Posição simulada";
  for (const name of ["stand", "lie", "stop"]) {
    $("robot-" + name).disabled = !snapshot.robo?.conectado;
  }
  updateReadings();
  scheduleRender();
}

function handleBackendEvent(event) {
  const data = event.dados;
  if (event.tipo === "snapshot" || event.tipo === "estado") {
    applySnapshot({...integration.snapshot, ...data}, event.tipo === "snapshot");
  } else if (event.tipo === "pose") {
    const pose = poseForDisplay(data);
    if (pose && integration.snapshot?.robo?.conectado) {
      integration.snapshot.pose = data;
      acceptPose(pose);
    }
  } else if (event.tipo === "leitura") {
    state.radiation = data;
    if (integration.snapshot) integration.snapshot.leitura = data;
    updateReadings();
  } else if (event.tipo === "amostra" && state.missionId != null) {
    if (appendSample(data)) integration.sampleCount += 1;
    updateReadings();
  } else if (event.tipo === "estimativa" && data?.missao_id === state.missionId && Number.isFinite(data.n)) {
    integration.sampleCount = Math.max(integration.sampleCount, data.n);
    updateReadings();
  }
}

// Reuse the approved visual layout and robot drawing, without a virtual pose
// when the real robot is unavailable or without converting CPS to dose.
fallbackPose = () => null;
const approvedDrawRobot = drawRobot;
drawRobot = (plot, pose) => { if (pose) approvedDrawRobot(plot, pose); };
colorMinimum = () => 1;
colorMaximum = () => Math.max(10, ...state.mapped.map(sample => sample.cps));
formatRateWithUnit = (value) => `${formatNumber(value, value >= 10 ? 0 : 1)} CPS`;
drawWaitingState = (plot) => {
  if (state.pose) return;
  context.save();
  context.fillStyle = "#b3c4d2";
  context.font = "700 16px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.fillText("Aguardando posição do Go2", plot.left + plot.width / 2, plot.top + plot.height / 2);
  context.restore();
};
updateReadings = () => {
  const reading = state.radiation;
  const age = reading?.ts == null ? Infinity : (Date.now() / 1000 - reading.ts);
  const live = integration.telemetry?.readyState === WebSocket.OPEN
    && integration.snapshot?.radiacao?.conectado && age >= -0.5 && age < 3;
  $("usb-cps").textContent = live && reading.cps != null ? String(reading.cps) : "—";
  $("usb-age").textContent = Number.isFinite(age)
    ? `${Math.max(0, age).toFixed(1)} s desde a leitura` : "Aguardando USB";
  $("usb-age").style.color = live ? "#80e0c0" : "#ffb078";
  $("dose-rate").textContent = live && reading.dr_usvh != null ? formatDoseRate(reading.dr_usvh) : "—";
  $("dose-rate-unit").textContent = live && reading.dr_usvh != null ? scaledDoseRate(reading.dr_usvh).unit : "µSv/h";
  // Cumulative dose is unavailable in this integration. Do not invent zero
  // or integrate the provisional dose-rate conversion in the browser.
  $("dose-total").textContent = "—";
  $("sample-count").textContent = String(Math.max(integration.sampleCount, integration.snapshot?.missao?.n_amostras ?? 0));
};

function socketUrl(path) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}
function openCommands() {
  if (integration.stopped || [WebSocket.OPEN, WebSocket.CONNECTING].includes(integration.commands?.readyState)) return;
  const socket = new WebSocket(socketUrl("/ws/comando"));
  integration.commands = socket;
  socket.onopen = () => { state.pressedKeys.clear(); sendCurrentCommand(); };
  socket.onclose = () => {
    state.pressedKeys.clear();
    if (!integration.stopped && integration.telemetry?.readyState === WebSocket.OPEN) {
      window.setTimeout(openCommands, 1000);
    }
  };
  socket.onerror = () => state.pressedKeys.clear();
}
sendCurrentCommand = () => {
  const socket = integration.commands;
  if (socket?.readyState !== WebSocket.OPEN) return;
  if (socket.bufferedAmount > 4096) { state.pressedKeys.clear(); socket.close(); return; }
  const enabled = state.missionState === "RUNNING"
    && integration.telemetry?.readyState === WebSocket.OPEN && integration.snapshot?.robo?.conectado;
  const command = enabled ? currentCommand() : {linear_m_s: 0, yaw_rate_rad_s: 0};
  socket.send(JSON.stringify({vx: command.linear_m_s, vy: 0, vyaw: command.yaw_rate_rad_s}));
};
stopRobot = () => { state.pressedKeys.clear(); sendCurrentCommand(); };

function openTelemetry() {
  if (integration.stopped) return;
  const socket = new WebSocket(socketUrl("/ws"));
  integration.telemetry = socket;
  socket.onopen = () => { setConnected(true); openCommands(); };
  socket.onmessage = (event) => {
    try { handleBackendEvent(JSON.parse(event.data)); }
    catch (error) { setMessage(`Falha na telemetria: ${error.message}`, true); }
  };
  socket.onerror = () => setConnected(false);
  socket.onclose = () => {
    stopRobot();
    integration.commands?.close();
    setConnected(false);
    updateReadings();
    if (!integration.stopped) window.setTimeout(openTelemetry, 1000);
  };
}

async function missionAction(start) {
  stopRobot();
  integration.pending = true;
  $("start-button").disabled = true;
  $("end-button").disabled = true;
  try {
    const result = await backend(`/missao/${start ? "iniciar" : "encerrar"}`, {
      method: "POST", ...(start ? {body: JSON.stringify({nome: "Radiacode USB + Go2"})} : {}),
    });
    showExports(result.id);
    applySnapshot(await backend("/estado"));
    setMessage(start ? "Missão ativa. Use as setas para mover o Go2." : "Missão salva. CSV e JSON disponíveis.");
  } catch (error) { setMessage(`Não foi possível ${start ? "iniciar" : "encerrar"}: ${error.message}`, true); }
  finally {
    integration.pending = false;
    if (integration.snapshot) applySnapshot(integration.snapshot);
  }
}

function startIntegration() {
  state.scenario = {world: {bounds_m: {x_min: -10000, x_max: 10000, y_min: -10000, y_max: 10000}}};
  $("start-button").addEventListener("click", () => void missionAction(true));
  $("end-button").addEventListener("click", () => void missionAction(false));
  for (const [name, action] of [["stand", "levantar"], ["lie", "deitar"], ["stop", "parar"]]) {
    const button = $("robot-" + name);
    button.disabled = true;
    button.addEventListener("click", async () => {
      stopRobot(); button.disabled = true;
      try {
        await backend(`/robo/${action}`, {method: "POST"});
        setMessage(`Comando ${action} enviado.`);
      } catch (error) { setMessage(`Comando indisponível: ${error.message}`, true); }
      finally { button.disabled = !integration.snapshot?.robo?.conectado; }
    });
  }
  const arrows = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
  window.addEventListener("keydown", event => {
    if (!arrows.has(event.key) || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    event.preventDefault();
    if (state.missionState !== "RUNNING" || integration.commands?.readyState !== WebSocket.OPEN) return;
    state.pressedKeys.add(event.key);
    sendCurrentCommand();
  });
  window.addEventListener("keyup", event => {
    if (!arrows.has(event.key)) return;
    event.preventDefault(); state.pressedKeys.delete(event.key); sendCurrentCommand();
  });
  window.addEventListener("blur", stopRobot);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopRobot(); });
  window.addEventListener("pagehide", () => {
    stopRobot(); integration.stopped = true;
    integration.commands?.close(); integration.telemetry?.close();
  });
  window.setInterval(() => { if (state.pressedKeys.size) sendCurrentCommand(); }, 100);
  window.setInterval(updateReadings, 250);
  if (window.ResizeObserver) new ResizeObserver(scheduleRender).observe(canvas);
  else window.addEventListener("resize", scheduleRender);
  openTelemetry();
  scheduleRender();
}
startIntegration();
