"use strict";

// Adaptação exclusiva da demonstração; não é carregada nos modos USB.
const simulationBackend = backend;
backend = (path, options = {}) => {
  if (path === "/missao/iniciar") {
    options = {...options, body: JSON.stringify({nome: "Fonte e robô simulados"})};
  }
  return simulationBackend(path, options);
};

const simulationSnapshot = applySnapshot;
applySnapshot = (snapshot, recover = false) => {
  simulationSnapshot(snapshot, recover);
  $("integration-mode").textContent = "Radiação simulada · posição simulada";
  $("device-status").textContent = "Detector simulado · robô simulado · nenhum dispositivo físico";
  $("sim-apply").disabled = snapshot.missao?.id != null;
  const source = snapshot.fonte_sim;
  state.configuredSource = source ? {enabled: true, x_m: source.x, y_m: source.y,
    dose_rate_at_1m_uSv_h: source.s, background_uSv_h: 0.15} : null;
  scheduleRender();
};

const simulationReadings = updateReadings;
updateReadings = () => {
  simulationReadings();
  const age = state.radiation?.ts == null ? Infinity : Date.now() / 1000 - state.radiation.ts;
  $("usb-age").textContent = Number.isFinite(age)
    ? `${Math.max(0, age).toFixed(1)} s desde a leitura simulada` : "Aguardando simulação";
};

$("sim-apply").addEventListener("click", async () => {
  const x = Number($("sim-x").value), y = Number($("sim-y").value);
  const s = Number($("sim-strength").value);
  if (![x, y, s].every(Number.isFinite) || s <= 0) {
    setMessage("Informe coordenadas válidas e intensidade maior que zero.", true);
    return;
  }
  try {
    await backend("/simulacao/fonte", {method: "POST", body: JSON.stringify({x, y, s})});
    applySnapshot(await backend("/estado"));
    setMessage("Fonte aplicada. Inicie uma missão e mova o robô com as setas.");
  } catch (error) { setMessage(`Não foi possível aplicar a fonte: ${error.message}`, true); }
});

// A fonte sempre fica no enquadramento, inclusive quando é reposicionada.
const simulationBounds = viewTargetBounds;
viewTargetBounds = () => {
  const bounds = simulationBounds();
  const source = state.configuredSource;
  if (!bounds || !source?.enabled) return bounds;
  return {x_min: Math.min(bounds.x_min, source.x_m - 2),
    x_max: Math.max(bounds.x_max, source.x_m + 2),
    y_min: Math.min(bounds.y_min, source.y_m - 2),
    y_max: Math.max(bounds.y_max, source.y_m + 2)};
};

void backend("/estado").then(snapshot => applySnapshot(snapshot))
  .catch(error => setMessage(`Falha na simulação: ${error.message}`, true));
