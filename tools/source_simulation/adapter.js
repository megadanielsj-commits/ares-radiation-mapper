"use strict";

const sourceDisplay = {field: null, lastMission: null, measuredMaximum: 10,
  frameMaximum: null, raster: null};

function acceptSourceEstimate(result) {
  const mission = state.missionId ?? integration.savedMission;
  if (result?.missao_id !== mission) return;
  sourceDisplay.field = fieldFromEstimate(result, window.ARES_SIMULATION_MODEL);
  if (integration.snapshot) integration.snapshot.resultado = result;
  $("map-mode").textContent = sourceDisplay.field
    ? (sourceDisplay.field.partial ? "Campo estimado · cobertura parcial" : "Campo estimado")
    : "Aguardando medições";
  scheduleRender();
}

// A grade medida local continua no backend. Esta demonstração apresenta
// o campo previsto pelo estimador em toda a área, com legenda explícita.
acceptMeasuredMap = () => {};

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
  const id = snapshot.missao?.id ?? null;
  if (id != null && id !== sourceDisplay.lastMission) {
    sourceDisplay.field = null;
    sourceDisplay.measuredMaximum = 10;
    sourceDisplay.raster = null;
    sourceDisplay.lastMission = id;
  }
  simulationSnapshot(snapshot, recover);
  $("integration-mode").textContent = "Radiação simulada · posição simulada";
  $("device-status").textContent = "Detector simulado · robô simulado · nenhum dispositivo físico";
  $("sim-apply").disabled = snapshot.missao?.id != null;
  const source = snapshot.fonte_sim;
  state.configuredSource = source ? {enabled: true, x_m: source.x, y_m: source.y,
    dose_rate_at_1m_uSv_h: source.s, background_uSv_h: 0.15} : null;
  acceptSourceEstimate(snapshot.resultado);
  if (!sourceDisplay.field) $("map-mode").textContent = "Aguardando medições";
  scheduleRender();
};

const sourceEvent = handleBackendEvent;
handleBackendEvent = (event) => {
  sourceEvent(event);
  if (event.tipo === "estimativa") acceptSourceEstimate(event.dados);
};

// Uma escala por quadro: raster, pontos antigos e legenda usam os mesmos
// limites. O raster é refeito quando chega uma estimativa ou um novo máximo.
const sourceFrame = renderMapNow;
renderMapNow = (timestamp) => {
  for (const sample of state.mapped) sourceDisplay.measuredMaximum = Math.max(sourceDisplay.measuredMaximum, sample.cps);
  sourceDisplay.frameMaximum = Math.max(10, sourceDisplay.measuredMaximum,
    estimatedPeakCounts(sourceDisplay.field));
  sourceFrame(timestamp);
  sourceDisplay.frameMaximum = null;
};
colorMaximum = () => sourceDisplay.frameMaximum ?? Math.max(10,
  sourceDisplay.measuredMaximum, ...state.mapped.map(sample => sample.cps),
  estimatedPeakCounts(sourceDisplay.field));

drawHeatmap = (plot) => {
  const field = sourceDisplay.field;
  if (!field) return false;
  const size = 160;
  const bounds = plot.bounds;
  const key = JSON.stringify([field, bounds, colorMinimum(), colorMaximum()]);
  if (sourceDisplay.raster?.key !== key) {
    const offscreen = document.createElement("canvas");
    offscreen.width = size; offscreen.height = size;
    const offscreenContext = offscreen.getContext("2d");
    const pixels = offscreenContext.createImageData(size, size);
    const minimum = colorMinimum();
    const logMinimum = Math.log10(minimum);
    const logRange = Math.log10(colorMaximum()) - logMinimum;
    const palette = [];
    for (let step = 0; step < 256; step += 1) {
      palette.push(radiationColor(10 ** (logMinimum + step / 255 * logRange)).rgb);
    }
    for (let row = 0; row < size; row += 1) {
      const y = bounds.y_max - (row + .5) / size * (bounds.y_max - bounds.y_min);
      for (let column = 0; column < size; column += 1) {
        const x = bounds.x_min + (column + .5) / size * (bounds.x_max - bounds.x_min);
        const value = Math.max(minimum, estimatedCounts(field, x, y));
        const index = Math.max(0, Math.min(255,
          Math.round((Math.log10(value) - logMinimum) / logRange * 255)));
        const color = palette[index];
        const offset = (row * size + column) * 4;
        pixels.data[offset] = color[0]; pixels.data[offset+1] = color[1];
        pixels.data[offset+2] = color[2]; pixels.data[offset+3] = 238;
      }
    }
    offscreenContext.putImageData(pixels, 0, 0);
    sourceDisplay.raster = {key, canvas: offscreen};
  }
  context.save();
  context.beginPath(); context.rect(plot.left, plot.top, plot.width, plot.height); context.clip();
  context.imageSmoothingEnabled = true; context.imageSmoothingQuality = "high";
  context.drawImage(sourceDisplay.raster.canvas, plot.left, plot.top, plot.width, plot.height);
  context.restore();
  return true;
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
    sourceDisplay.field = null;
    sourceDisplay.raster = null;
    sourceDisplay.measuredMaximum = 10;
    integration.savedMission = null;
    integration.sampleKeys.clear();
    integration.sampleCount = 0;
    state.mapped = [];
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
