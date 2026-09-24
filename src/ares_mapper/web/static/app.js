"use strict";

const state = {
  scenario: null,
  configuredSource: null,
  missionId: null,
  missionState: "READY",
  pose: null,
  displayPose: null,
  lastPoseRenderTimestampMs: null,
  radiation: null,
  mapped: [],
  map: null,
  accumulatedDose: 0,
  socket: null,
  pressedKeys: new Set(),
  lastCommand: null,
  renderFrame: null,
  plotGeometry: null,
};

const $ = (id) => document.getElementById(id);
const apiRoot = "/api/v1";
const microSievertsPerMilliSievert = 1_000;
const canvas = $("radiation-map");
const context = canvas.getContext("2d", {alpha: false});

async function api(path, options = {}) {
  const response = await fetch(`${apiRoot}${path}`, {
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP message when an endpoint does not return JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

function sourceValue(frames, key, fallback = 0) {
  if (!Array.isArray(frames) || !frames.length) return fallback;
  return Number(frames[frames.length - 1][key] ?? fallback);
}

function initialSourceFromScenario() {
  const source = state.scenario?.radiation_sources?.[0];
  if (!source) return null;
  return {
    id: source.id,
    x_m: sourceValue(source.position_keyframes, "x_m"),
    y_m: sourceValue(source.position_keyframes, "y_m"),
    z_m: sourceValue(source.position_keyframes, "z_m", 0.8),
    dose_rate_at_1m_uSv_h: sourceValue(
      source.strength_keyframes,
      "dose_rate_at_reference_uSv_h",
    ),
    background_uSv_h: Number(
      state.scenario?.world?.background?.dose_rate_uSv_h ?? 0,
    ),
    enabled: source.enabled !== false,
  };
}

function mapBounds() {
  return state.scenario?.world?.bounds_m || {
    x_min: 0,
    x_max: 10,
    y_min: 0,
    y_max: 8,
  };
}

// Auto-zoom: enquadra o robô e os pontos medidos, para que a representação não
// fique minúscula quando os limites do mundo são amplos. mapBounds() continua
// sendo os limites reais do mundo (usado na validação e como teto do zoom).
const VIEW_MIN_SPAN_M = 16;
const VIEW_PADDING = 0.18;
const VIEW_SMOOTH_ALPHA = 0.15;

function viewTargetBounds() {
  const world = mapBounds();
  const points = [];
  const pose = finitePose(state.displayPose);
  if (pose) points.push([pose.x_m, pose.y_m]);
  for (const sample of state.mapped) {
    const x = Number(sample.sensor_x_m);
    const y = Number(sample.sensor_y_m);
    if (Number.isFinite(x) && Number.isFinite(y)) points.push([x, y]);
  }
  if (!points.length) return null;
  let xMin = Infinity;
  let xMax = -Infinity;
  let yMin = Infinity;
  let yMax = -Infinity;
  for (const [x, y] of points) {
    xMin = Math.min(xMin, x);
    xMax = Math.max(xMax, x);
    yMin = Math.min(yMin, y);
    yMax = Math.max(yMax, y);
  }
  const worldWidth = Math.max(1e-6, world.x_max - world.x_min);
  const worldHeight = Math.max(1e-6, world.y_max - world.y_min);
  const spanX = Math.min(
    Math.max((xMax - xMin) * (1 + VIEW_PADDING * 2), VIEW_MIN_SPAN_M),
    worldWidth,
  );
  const spanY = Math.min(
    Math.max((yMax - yMin) * (1 + VIEW_PADDING * 2), VIEW_MIN_SPAN_M),
    worldHeight,
  );
  const clamp = (center, span, lo, hi) =>
    Math.min(Math.max(center, lo + span / 2), hi - span / 2);
  const cx = clamp((xMin + xMax) / 2, spanX, world.x_min, world.x_max);
  const cy = clamp((yMin + yMax) / 2, spanY, world.y_min, world.y_max);
  return {
    x_min: cx - spanX / 2,
    x_max: cx + spanX / 2,
    y_min: cy - spanY / 2,
    y_max: cy + spanY / 2,
  };
}

function viewBounds() {
  const target = viewTargetBounds();
  if (!target) return state.viewBox || mapBounds();
  if (!state.viewBox) {
    state.viewBox = {...target};
    return state.viewBox;
  }
  const box = state.viewBox;
  box.x_min += (target.x_min - box.x_min) * VIEW_SMOOTH_ALPHA;
  box.x_max += (target.x_max - box.x_max) * VIEW_SMOOTH_ALPHA;
  box.y_min += (target.y_min - box.y_min) * VIEW_SMOOTH_ALPHA;
  box.y_max += (target.y_max - box.y_max) * VIEW_SMOOTH_ALPHA;
  return box;
}

function fallbackPose() {
  const start = state.scenario?.trajectory?.start_m || [2, 2, 0.32];
  return {
    x_m: Number(start[0]),
    y_m: Number(start[1]),
    z_m: Number(start[2]),
    yaw_rad: Number(state.scenario?.trajectory?.yaw_start_rad || 0),
  };
}

function robotGeometry() {
  const robot = state.scenario?.robot || {};
  const lengthM = Math.max(Number(robot.length_m) || 0.70, 1e-6);
  const widthM = Math.max(Number(robot.width_m) || 0.31, 1e-6);
  return {
    lengthM,
    widthM,
    heightM: Math.max(Number(robot.height_m) || 0.40, 1e-6),
    minimumDisplayLengthPx: Math.max(
      Number(robot.minimum_display_length_px) || 30,
      1,
    ),
    smoothingTimeConstantS: Math.max(
      Number(robot.visual_smoothing_time_constant_s) || 0,
      0,
    ),
  };
}

function normaliseAngle(angle) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

function shortestAngleDelta(from, to) {
  return normaliseAngle(to - from);
}

function finitePose(pose) {
  if (!pose) return null;
  const x = Number(pose.x_m);
  const y = Number(pose.y_m);
  const z = Number(pose.z_m || 0);
  const yaw = Number(pose.yaw_rad || 0);
  if (![x, y, z, yaw].every(Number.isFinite)) return null;
  return {...pose, x_m: x, y_m: y, z_m: z, yaw_rad: normaliseAngle(yaw)};
}

function acceptPose(pose, snap = false) {
  const next = finitePose(pose);
  if (!next) return;
  state.pose = next;
  if (!state.displayPose || snap) {
    state.displayPose = {...next};
    state.lastPoseRenderTimestampMs = null;
  }
  scheduleRender();
}

function displayPoseForFrame(timestampMs) {
  const target = finitePose(state.pose) || finitePose(fallbackPose());
  if (!target) return fallbackPose();
  if (!state.displayPose) {
    state.displayPose = {...target};
    state.lastPoseRenderTimestampMs = timestampMs;
    return state.displayPose;
  }
  const previousTimestamp = state.lastPoseRenderTimestampMs;
  state.lastPoseRenderTimestampMs = timestampMs;
  if (previousTimestamp == null) return state.displayPose;
  const deltaS = clamp((timestampMs - previousTimestamp) / 1_000, 0, 0.10);
  const timeConstantS = robotGeometry().smoothingTimeConstantS;
  const alpha = timeConstantS <= 0
    ? 1
    : 1 - Math.exp(-deltaS / timeConstantS);
  state.displayPose.x_m += (target.x_m - state.displayPose.x_m) * alpha;
  state.displayPose.y_m += (target.y_m - state.displayPose.y_m) * alpha;
  state.displayPose.z_m += (target.z_m - state.displayPose.z_m) * alpha;
  state.displayPose.yaw_rad = normaliseAngle(
    state.displayPose.yaw_rad
      + shortestAngleDelta(state.displayPose.yaw_rad, target.yaw_rad) * alpha,
  );
  return state.displayPose;
}

function displayPoseNeedsAnimation() {
  const target = finitePose(state.pose);
  const displayed = finitePose(state.displayPose);
  if (!target || !displayed) return false;
  return (
    Math.hypot(target.x_m - displayed.x_m, target.y_m - displayed.y_m) > 0.0005
    || Math.abs(shortestAngleDelta(displayed.yaw_rad, target.yaw_rad)) > 0.0005
  );
}

function numberFromInput(id) {
  return Number($(id).value.replace(",", "."));
}

function formatNumber(value, digits) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function setMessage(message, error = false) {
  $("action-message").textContent = message;
  $("action-message").classList.toggle("error", error);
}

function setConnected(connected) {
  const element = document.querySelector(".connection");
  element.classList.toggle("connected", connected);
  $("connection-label").textContent = connected ? "Conectado" : "Reconectando";
}

function colorMaximum() {
  const sourceRate = sourceRateForScaleUSvH();
  const background = backgroundRateUSvH();
  const physicalMinimum = Number(
    state.scenario?.mapping?.source_minimum_distance_m ?? 0.25,
  );
  const displayDistance = Math.max(0.5, physicalMinimum);
  return Math.max(
    0.25,
    background + sourceRate / (displayDistance * displayDistance),
  );
}

function colorMinimum() {
  const sourceRate = sourceRateForScaleUSvH();
  const background = backgroundRateUSvH();
  return Math.max(
    1e-6,
    background > 0 ? background : Math.max(sourceRate / 1_000_000, 1e-3),
  );
}

function sourceRateForScaleUSvH() {
  if (isUsbTest()) {
    const measuredRate = Number(
      state.radiation?.dose_rate_uSv_h
        ?? state.mapped.at(-1)?.dose_rate_uSv_h_filtered,
    );
    // The USB scenario has no configured source. Scale the map from real
    // measurements without consulting controls removed from the USB panel.
    return Math.max(Number.isFinite(measuredRate) ? measuredRate : 0, 0.25);
  }
  const inputRateMSvH = numberFromInput("source-strength");
  const inputRateUSvH = inputRateMSvH * microSievertsPerMilliSievert;
  return Math.max(
    Number(
      state.configuredSource?.dose_rate_at_1m_uSv_h
        ?? (Number.isFinite(inputRateUSvH) ? inputRateUSvH : 10_000),
    ),
    1e-12,
  );
}

function maximumSourceRateUSvH() {
  const inputMaximumMSvH = Number($("source-strength").max);
  return Number.isFinite(inputMaximumMSvH) && inputMaximumMSvH > 0
    ? inputMaximumMSvH * microSievertsPerMilliSievert
    : 10_000_000;
}

function publicReferenceRateUSvH() {
  return Math.max(
    Number(
      state.scenario?.dashboard?.public_reference_rate_uSv_h
        ?? (1_000 / (365 * 24)),
    ),
    1e-12,
  );
}

function dashboardRateUSvH(key, fallback) {
  return Math.max(
    Number(state.scenario?.dashboard?.[key] ?? fallback),
    1e-12,
  );
}

function ioeRecordingRateUSvH() {
  return dashboardRateUSvH("ioe_recording_rate_uSv_h", 0.5);
}

function ioeInvestigationRateUSvH() {
  return dashboardRateUSvH("ioe_investigation_rate_uSv_h", 3);
}

function ioeLimitRateUSvH() {
  return dashboardRateUSvH("ioe_limit_rate_uSv_h", 10);
}

function ioeMaximumRateUSvH() {
  return dashboardRateUSvH("ioe_maximum_rate_uSv_h", 25);
}

function backgroundRateUSvH() {
  return Math.max(
    0,
    Number(
      state.configuredSource?.background_uSv_h
        ?? state.scenario?.world?.background?.dose_rate_uSv_h
        ?? 0,
    ),
  );
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function excessRateUSvH(totalRateUSvH) {
  const total = Math.max(Number(totalRateUSvH) || 0, 0);
  return Math.max(total - backgroundRateUSvH(), 0);
}

function colorFractionForTotalRate(totalRate) {
  const minimum = colorMinimum();
  const maximum = colorMaximum();
  const safeMaximum = Math.max(maximum, minimum * 1.000001);
  const value = clamp(Number(totalRate) || 0, minimum, safeMaximum);
  return clamp(
    (Math.log10(value) - Math.log10(minimum))
      / (Math.log10(safeMaximum) - Math.log10(minimum)),
    0,
    1,
  );
}

const radiationStops = [
  {position: 0.00, rgb: [11, 27, 42]},
  {position: 0.16, rgb: [28, 87, 111]},
  {position: 0.35, rgb: [57, 151, 145]},
  {position: 0.54, rgb: [218, 195, 103]},
  {position: 0.74, rgb: [230, 116, 71]},
  {position: 1.00, rgb: [183, 35, 58]},
];

function regulatoryBandForExcessRate(excessRate) {
  const rate = Math.max(Number(excessRate) || 0, 0);
  if (rate <= publicReferenceRateUSvH()) return "Dentro da referência do público";
  if (rate < ioeRecordingRateUSvH()) return "Acima da referência do público";
  if (rate < ioeInvestigationRateUSvH()) return "Nível de registro do IOE";
  if (rate < ioeLimitRateUSvH()) return "Nível de investigação do IOE";
  if (rate < ioeMaximumRateUSvH()) return "Acima do limite anual do IOE";
  return "Acima do teto anual do IOE";
}

function radiationColor(value, alpha = 1) {
  const fraction = colorFractionForTotalRate(value);
  let lower = radiationStops[0];
  let upper = radiationStops[radiationStops.length - 1];
  for (let index = 1; index < radiationStops.length; index += 1) {
    if (fraction <= radiationStops[index].position) {
      lower = radiationStops[index - 1];
      upper = radiationStops[index];
      break;
    }
  }
  const width = Math.max(upper.position - lower.position, 1e-9);
  const mix = (fraction - lower.position) / width;
  const rgb = lower.rgb.map((channel, index) => (
    Math.round(channel + (upper.rgb[index] - channel) * mix)
  ));
  return {rgb, css: `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`};
}

function resizeCanvas() {
  const bounds = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(bounds.width));
  const height = Math.max(1, Math.round(bounds.height));
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const targetWidth = Math.round(width * pixelRatio);
  const targetHeight = Math.round(height * pixelRatio);
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
  }
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  return {width, height};
}

function calculatePlotGeometry(width, height) {
  const bounds = viewBounds();
  const margin = {
    left: width < 800 ? 58 : 72,
    right: width < 800 ? 105 : 145,
    top: 28,
    bottom: 58,
  };
  const availableWidth = Math.max(40, width - margin.left - margin.right);
  const availableHeight = Math.max(40, height - margin.top - margin.bottom);
  const worldWidth = Math.max(1e-9, bounds.x_max - bounds.x_min);
  const worldHeight = Math.max(1e-9, bounds.y_max - bounds.y_min);
  const scale = Math.min(
    availableWidth / worldWidth,
    availableHeight / worldHeight,
  );
  const plotWidth = worldWidth * scale;
  const plotHeight = worldHeight * scale;
  const left = margin.left + (availableWidth - plotWidth) / 2;
  const top = margin.top + (availableHeight - plotHeight) / 2;
  return {
    bounds,
    left,
    top,
    width: plotWidth,
    height: plotHeight,
    right: left + plotWidth,
    bottom: top + plotHeight,
    scale,
    xToPixel: (x) => left + (Number(x) - bounds.x_min) * scale,
    yToPixel: (y) => top + (bounds.y_max - Number(y)) * scale,
    pixelToX: (x) => bounds.x_min + (x - left) / scale,
    pixelToY: (y) => bounds.y_max - (y - top) / scale,
  };
}

function niceGridStep(span) {
  const raw = span / 9;
  const exponent = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  const normalized = raw / exponent;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return factor * exponent;
}

function drawMapBackground(plot) {
  context.fillStyle = "#07111b";
  context.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  context.fillStyle = "#0a1723";
  context.fillRect(plot.left, plot.top, plot.width, plot.height);
  context.strokeStyle = "#31465b";
  context.lineWidth = 1;
  context.strokeRect(plot.left + 0.5, plot.top + 0.5, plot.width - 1, plot.height - 1);
}

function drawHeatmap(plot) {
  const payload = state.map;
  if (!payload?.values_row_major?.length || !payload.grid_shape) return false;
  const [rows, columns] = payload.grid_shape.map(Number);
  if (
    rows <= 0
    || columns <= 0
    || rows * columns !== payload.values_row_major.length
  ) {
    return false;
  }
  const offscreen = document.createElement("canvas");
  offscreen.width = columns;
  offscreen.height = rows;
  const offscreenContext = offscreen.getContext("2d");
  const image = offscreenContext.createImageData(columns, rows);
  let finiteCount = 0;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const raw = payload.values_row_major[row * columns + column];
      if (raw == null || !Number.isFinite(Number(raw))) continue;
      finiteCount += 1;
      const {rgb} = radiationColor(Number(raw));
      const canvasRow = rows - row - 1;
      const offset = (canvasRow * columns + column) * 4;
      image.data[offset] = rgb[0];
      image.data[offset + 1] = rgb[1];
      image.data[offset + 2] = rgb[2];
      image.data[offset + 3] = 238;
    }
  }
  if (!finiteCount) return false;
  offscreenContext.putImageData(image, 0, 0);
  context.save();
  context.beginPath();
  context.rect(plot.left, plot.top, plot.width, plot.height);
  context.clip();
  context.globalAlpha = 0.96;
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    offscreen,
    plot.left,
    plot.top,
    plot.width,
    plot.height,
  );
  context.restore();
  return true;
}

function drawGridAndAxes(plot) {
  const {bounds} = plot;
  const xStep = niceGridStep(bounds.x_max - bounds.x_min);
  const yStep = niceGridStep(bounds.y_max - bounds.y_min);

  context.save();
  context.font = "12px Inter, system-ui, sans-serif";
  context.textBaseline = "middle";
  context.lineWidth = 1;

  for (
    let x = Math.ceil(bounds.x_min / xStep) * xStep;
    x <= bounds.x_max + xStep * 1e-6;
    x += xStep
  ) {
    const pixel = plot.xToPixel(x);
    context.strokeStyle = "rgba(127, 154, 178, 0.19)";
    context.beginPath();
    context.moveTo(pixel, plot.top);
    context.lineTo(pixel, plot.bottom);
    context.stroke();
    context.fillStyle = "#8197aa";
    context.textAlign = "center";
    context.fillText(formatAxisValue(x, xStep), pixel, plot.bottom + 22);
  }

  for (
    let y = Math.ceil(bounds.y_min / yStep) * yStep;
    y <= bounds.y_max + yStep * 1e-6;
    y += yStep
  ) {
    const pixel = plot.yToPixel(y);
    context.strokeStyle = "rgba(127, 154, 178, 0.19)";
    context.beginPath();
    context.moveTo(plot.left, pixel);
    context.lineTo(plot.right, pixel);
    context.stroke();
    context.fillStyle = "#8197aa";
    context.textAlign = "right";
    context.fillText(formatAxisValue(y, yStep), plot.left - 12, pixel);
  }

  context.fillStyle = "#9aafc1";
  context.font = "600 12px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.fillText("Coordenada X [m]", plot.left + plot.width / 2, plot.bottom + 46);

  context.save();
  context.translate(plot.left - 48, plot.top + plot.height / 2);
  context.rotate(-Math.PI / 2);
  context.fillText("Coordenada Y [m]", 0, 0);
  context.restore();
  context.restore();
}

function formatAxisValue(value, step) {
  const digits = step < 1 ? 1 : 0;
  return Number(value).toFixed(digits).replace(".", ",");
}

function drawColorBar(plot) {
  const minimum = colorMinimum();
  const maximum = colorMaximum();
  const width = 13;
  const height = Math.min(300, plot.height * 0.62);
  const left = plot.right + 26;
  const top = plot.top + (plot.height - height) / 2;
  const gradient = context.createLinearGradient(0, top + height, 0, top);
  for (const stop of radiationStops) {
    const [red, green, blue] = stop.rgb;
    gradient.addColorStop(stop.position, `rgb(${red}, ${green}, ${blue})`);
  }
  context.fillStyle = gradient;
  context.fillRect(left, top, width, height);
  context.strokeStyle = "#40566a";
  context.strokeRect(left + 0.5, top + 0.5, width - 1, height - 1);

  context.font = "11px Inter, system-ui, sans-serif";
  context.fillStyle = "#8da3b6";
  context.textAlign = "left";
  context.textBaseline = "middle";
  for (const fraction of [0, 0.25, 0.5, 0.75, 1]) {
    const y = top + height * (1 - fraction);
    context.strokeStyle = "#7890a4";
    context.beginPath();
    context.moveTo(left + width, y);
    context.lineTo(left + width + 5, y);
    context.stroke();
    context.fillText(
      formatRateWithUnit(
        10 ** (
          Math.log10(minimum)
          + fraction * (Math.log10(maximum) - Math.log10(minimum))
        ),
        true,
      ),
      left + width + 9,
      y,
    );
  }
  context.fillStyle = "#b3c4d2";
  context.font = "700 11px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.fillText("taxa estimada", left + width / 2 + 34, top - 15);
}

function scaledDoseRate(valueUSvH) {
  const number = Number(valueUSvH);
  if (!Number.isFinite(number)) return {value: NaN, unit: ""};
  if (Math.abs(number) >= 1_000_000) {
    return {value: number / 1_000_000, unit: "Sv/h"};
  }
  if (Math.abs(number) >= 1_000) {
    return {value: number / 1_000, unit: "mSv/h"};
  }
  return {value: number, unit: "µSv/h"};
}

function formatDoseRate(value) {
  const scaled = scaledDoseRate(value);
  if (!Number.isFinite(scaled.value)) return "—";
  const magnitude = Math.abs(scaled.value);
  const digits = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 3;
  return formatNumber(scaled.value, digits);
}

function formatRateWithUnit(value, compact = false) {
  const scaled = scaledDoseRate(value);
  if (!Number.isFinite(scaled.value)) return "—";
  const magnitude = Math.abs(scaled.value);
  const digits = compact
    ? (magnitude >= 10 ? 0 : magnitude >= 1 ? 1 : 3)
    : (magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 3);
  return `${formatNumber(scaled.value, digits)} ${scaled.unit}`;
}

function scaledDose(valueUSv) {
  const number = Number(valueUSv);
  if (!Number.isFinite(number)) return {value: NaN, unit: ""};
  if (Math.abs(number) >= 1_000_000) {
    return {value: number / 1_000_000, unit: "Sv"};
  }
  if (Math.abs(number) >= 1_000) {
    return {value: number / 1_000, unit: "mSv"};
  }
  return {value: number, unit: "µSv"};
}

function drawMeasuredPath(plot) {
  const samples = state.mapped.slice(-1200);
  if (!samples.length) return;
  context.save();
  context.beginPath();
  context.rect(plot.left, plot.top, plot.width, plot.height);
  context.clip();
  context.strokeStyle = "rgba(238, 244, 247, 0.72)";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.lineCap = "round";
  context.beginPath();
  samples.forEach((sample, index) => {
    const x = plot.xToPixel(sample.sensor_x_m);
    const y = plot.yToPixel(sample.sensor_y_m);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();

  const stride = Math.max(1, Math.floor(samples.length / 220));
  for (let index = 0; index < samples.length; index += stride) {
    const sample = samples[index];
    const x = plot.xToPixel(sample.sensor_x_m);
    const y = plot.yToPixel(sample.sensor_y_m);
    context.fillStyle = radiationColor(sample.dose_rate_uSv_h_filtered).css;
    context.beginPath();
    context.arc(x, y, 3.2, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "#07111b";
    context.lineWidth = 1;
    context.stroke();
  }
  context.restore();
}

function drawSource(plot) {
  const source = state.configuredSource;
  if (!source?.enabled) return;
  const x = plot.xToPixel(source.x_m);
  const y = plot.yToPixel(source.y_m);
  if (x < plot.left || x > plot.right || y < plot.top || y > plot.bottom) return;
  const radius = 10;
  context.save();
  context.translate(x, y);
  context.rotate(Math.PI / 4);
  context.fillStyle = "#ef6a70";
  context.strokeStyle = "#fff3f3";
  context.lineWidth = 2;
  context.fillRect(-radius / 1.4, -radius / 1.4, radius * 1.4, radius * 1.4);
  context.strokeRect(-radius / 1.4, -radius / 1.4, radius * 1.4, radius * 1.4);
  context.restore();
  drawMarkerLabel("FONTE", x, y - 18, "#ffb4b8");
}

function robotPixelPoint(centerX, centerY, yaw, localX, localY) {
  const cos = Math.cos(yaw);
  const sin = Math.sin(yaw);
  return [
    centerX + localX * cos - localY * sin,
    centerY - localX * sin - localY * cos,
  ];
}

function traceRobotPolygon(points) {
  context.beginPath();
  points.forEach(([pixelX, pixelY], index) => {
    if (index === 0) context.moveTo(pixelX, pixelY);
    else context.lineTo(pixelX, pixelY);
  });
  context.closePath();
}

function drawRobot(plot, pose) {
  const x = Number(pose.x_m);
  const y = Number(pose.y_m);
  const yaw = Number(pose.yaw_rad || 0);
  if (![x, y, yaw].every(Number.isFinite)) return;
  const centerX = plot.xToPixel(x);
  const centerY = plot.yToPixel(y);
  const geometry = robotGeometry();
  const physicalLengthPx = geometry.lengthM * plot.scale;
  const physicalWidthPx = geometry.widthM * plot.scale;
  const displayLengthPx = Math.max(
    physicalLengthPx,
    geometry.minimumDisplayLengthPx,
  );
  const displayWidthPx = displayLengthPx * geometry.widthM / geometry.lengthM;
  const halfLengthPx = displayLengthPx / 2;
  const halfWidthPx = displayWidthPx / 2;
  const displayLocal = [
    [halfLengthPx, halfWidthPx],
    [halfLengthPx, -halfWidthPx],
    [-halfLengthPx, -halfWidthPx],
    [-halfLengthPx, halfWidthPx],
  ];
  const displayPoints = displayLocal.map(([dx, dy]) => (
    robotPixelPoint(centerX, centerY, yaw, dx, dy)
  ));
  context.save();
  context.beginPath();
  context.rect(plot.left, plot.top, plot.width, plot.height);
  context.clip();

  context.shadowColor = "rgba(104, 225, 207, 0.45)";
  context.shadowBlur = 8;
  traceRobotPolygon(displayPoints);
  context.fillStyle = "rgba(104, 225, 207, 0.34)";
  context.strokeStyle = "#68e1cf";
  context.lineWidth = 2.4;
  context.fill();
  context.stroke();
  context.shadowBlur = 0;

  const bodyHalfLength = halfLengthPx * 0.68;
  const bodyHalfWidth = halfWidthPx * 0.64;
  const bodyPoints = [
    [bodyHalfLength, bodyHalfWidth],
    [bodyHalfLength, -bodyHalfWidth],
    [-bodyHalfLength, -bodyHalfWidth],
    [-bodyHalfLength, bodyHalfWidth],
  ].map(([dx, dy]) => robotPixelPoint(centerX, centerY, yaw, dx, dy));
  traceRobotPolygon(bodyPoints);
  context.fillStyle = "rgba(232, 255, 251, 0.30)";
  context.fill();

  displayLocal.forEach(([dx, dy]) => {
    const [legX, legY] = robotPixelPoint(
      centerX,
      centerY,
      yaw,
      dx * 0.83,
      dy * 0.82,
    );
    context.fillStyle = "#b5fff4";
    context.beginPath();
    context.arc(legX, legY, 2.2, 0, Math.PI * 2);
    context.fill();
  });

  if (displayLengthPx > physicalLengthPx * 1.05) {
    const physicalHalfLength = physicalLengthPx / 2;
    const physicalHalfWidth = physicalWidthPx / 2;
    const physicalPoints = [
      [physicalHalfLength, physicalHalfWidth],
      [physicalHalfLength, -physicalHalfWidth],
      [-physicalHalfLength, -physicalHalfWidth],
      [-physicalHalfLength, physicalHalfWidth],
    ].map(([dx, dy]) => robotPixelPoint(centerX, centerY, yaw, dx, dy));
    context.setLineDash([2, 2]);
    context.strokeStyle = "rgba(232, 255, 251, 0.82)";
    context.lineWidth = 1;
    traceRobotPolygon(physicalPoints);
    context.stroke();
    context.setLineDash([]);
  }

  const [noseX, noseY] = robotPixelPoint(
    centerX,
    centerY,
    yaw,
    halfLengthPx * 1.18,
    0,
  );
  context.strokeStyle = "#e8fffb";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(centerX, centerY);
  context.lineTo(noseX, noseY);
  context.stroke();
  context.restore();
  const markerRadius = Math.hypot(halfLengthPx, halfWidthPx);
  drawMarkerLabel("GO2", centerX, centerY + markerRadius + 12, "#9ff3e6");
}

function drawMarkerLabel(text, x, y, color) {
  context.save();
  context.font = "800 10px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  const width = context.measureText(text).width + 10;
  context.fillStyle = "rgba(5, 12, 20, 0.82)";
  context.fillRect(x - width / 2, y - 8, width, 16);
  context.fillStyle = color;
  context.fillText(text, x, y);
  context.restore();
}

function drawWaitingState(plot, heatmapVisible) {
  if (heatmapVisible) return;
  const hasMeasurements = state.mapped.length > 0;
  const title = hasMeasurements
    ? "Calculando o primeiro gradiente"
    : "Aguardando a primeira medição";
  const detail = hasMeasurements
    ? "Os dados já foram recebidos e estão sendo processados."
    : "O mapa será atualizado automaticamente uma vez por segundo.";
  const centerX = plot.left + plot.width / 2;
  const centerY = plot.top + plot.height / 2;
  context.save();
  context.textAlign = "center";
  context.fillStyle = "rgba(5, 13, 22, 0.82)";
  context.strokeStyle = "#294256";
  context.lineWidth = 1;
  context.fillRect(centerX - 205, centerY - 43, 410, 86);
  context.strokeRect(centerX - 204.5, centerY - 42.5, 409, 85);
  context.fillStyle = "#dbe7f0";
  context.font = "700 16px Inter, system-ui, sans-serif";
  context.fillText(title, centerX, centerY - 10);
  context.fillStyle = "#8198ab";
  context.font = "12px Inter, system-ui, sans-serif";
  context.fillText(detail, centerX, centerY + 17);
  context.restore();
}

function renderMapNow(timestampMs) {
  state.renderFrame = null;
  if (!context) {
    setMessage("O navegador não oferece suporte ao mapa em Canvas.", true);
    return;
  }
  const {width, height} = resizeCanvas();
  if (width < 10 || height < 10) return;
  const frameTimestamp = Number.isFinite(timestampMs)
    ? timestampMs
    : performance.now();
  const plot = calculatePlotGeometry(width, height);
  state.plotGeometry = plot;
  drawMapBackground(plot);
  const heatmapVisible = drawHeatmap(plot);
  drawGridAndAxes(plot);
  drawMeasuredPath(plot);
  drawSource(plot);
  drawRobot(plot, displayPoseForFrame(frameTimestamp));
  drawWaitingState(plot, heatmapVisible);
  drawColorBar(plot);
  if (displayPoseNeedsAnimation()) scheduleRender();
}

function scheduleRender() {
  if (state.renderFrame != null) return;
  state.renderFrame = window.requestAnimationFrame(renderMapNow);
}

function updateReadings() {
  const rate = state.radiation?.dose_rate_uSv_h
    ?? state.mapped.at(-1)?.dose_rate_uSv_h_filtered;
  const rateDisplay = scaledDoseRate(rate);
  const doseDisplay = scaledDose(state.accumulatedDose);
  $("dose-rate").textContent = formatDoseRate(rate);
  $("dose-rate-unit").textContent = rateDisplay.unit || "mSv/h";
  $("dose-total").textContent = formatNumber(doseDisplay.value, 5);
  $("dose-total-unit").textContent = doseDisplay.unit || "µSv";
  $("sample-count").textContent = String(isUsbTest() ? (state.radiation?.sequence ?? 0) : state.mapped.length);
  if (isUsbTest()) {
    $("usb-cps").textContent = state.radiation?.cps == null ? "—" : Number(state.radiation.cps).toFixed(2);
    const received = Number(state.radiation?.received_utc_ns ?? 0) / 1e6;
    const age = received ? (Date.now() - received) / 1000 : Infinity;
    const live = age < 5;
    $("usb-age").textContent = received ? `${Math.max(0, age).toFixed(1)} s desde a leitura` : "Aguardando USB";
    $("usb-age").style.color = live ? "#80e0c0" : "#ffb078";
    if (!live) $("dose-rate").textContent = "—";
  }
}

function updateStatus(payload) {
  if (payload.mission_id) state.missionId = payload.mission_id;
  state.missionState = payload.state || state.missionState;
  if (payload.pose) acceptPose(payload.pose);
  if (payload.radiation) state.radiation = payload.radiation;
  const exposure = payload.exposure;
  if (exposure?.cumulative_robot_path_dose_uSv != null) {
    state.accumulatedDose = Number(exposure.cumulative_robot_path_dose_uSv);
  }
  if (state.missionState !== "RUNNING") {
    state.pressedKeys.clear();
    state.lastCommand = null;
  }
  updateReadings();
  scheduleRender();
}

function updateMap(payload) {
  state.map = payload;
  const exposure = payload.exposure;
  if (exposure?.cumulative_robot_path_dose_uSv != null) {
    state.accumulatedDose = Number(exposure.cumulative_robot_path_dose_uSv);
  }
  const mode = payload.metrics?.reconstruction_mode;
  if (mode === "physical_global") {
    $("map-mode").textContent = "Campo completo estabilizado";
    setMessage("Mapeamento ativo. O modelo global já está estabilizado.");
  } else if (mode === "physical_transition") {
    $("map-mode").textContent = "Transição para o campo completo";
    setMessage("Mapeamento ativo. O modelo físico está entrando gradualmente.");
  } else if (Number(payload.sample_count || 0) > 0) {
    $("map-mode").textContent = "Gradiente sustentado pelas medições";
    setMessage("Mapeamento ativo. Continue percorrendo posições diferentes.");
  } else {
    $("map-mode").textContent = "Aguardando primeira medição";
  }
  updateReadings();
  scheduleRender();
}

function handleEnvelope(envelope) {
  const payload = envelope.payload || {};
  if (
    state.missionId
    && payload.mission_id
    && payload.mission_id !== state.missionId
  ) {
    return;
  }
  if (envelope.type === "mission_state") {
    updateStatus(payload);
  } else if (envelope.type === "pose") {
    acceptPose(payload);
  } else if (envelope.type === "radiation") {
    state.radiation = payload;
    updateReadings();
  } else if (envelope.type === "mapped_sample") {
    state.mapped.push(payload);
    if (state.mapped.length > 5000) state.mapped.shift();
    state.accumulatedDose += (
      Number(payload.dose_rate_uSv_h_filtered || 0)
      * Number(payload.integration_time_s || 1)
      / 3600
    );
    updateReadings();
    scheduleRender();
  } else if (envelope.type === "map_update") {
    updateMap(payload);
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${protocol}://${window.location.host}/api/v1/ws/telemetry`,
  );
  state.socket = socket;
  socket.onopen = () => setConnected(true);
  socket.onmessage = (event) => {
    try {
      handleEnvelope(JSON.parse(event.data));
    } catch (error) {
      setMessage(`Falha ao ler telemetria: ${error.message}`, true);
    }
  };
  socket.onerror = () => setConnected(false);
  socket.onclose = () => {
    setConnected(false);
    window.setTimeout(connectWebSocket, 1000);
  };
}

function validateSetup() {
  const x = numberFromInput("source-x");
  const y = numberFromInput("source-y");
  const doseRateMSvH = numberFromInput("source-strength");
  const maximumSourceRateMSvH = (
    maximumSourceRateUSvH() / microSievertsPerMilliSievert
  );
  const bounds = mapBounds();
  if (!Number.isFinite(x) || x < bounds.x_min || x > bounds.x_max) {
    throw new Error(`X deve estar entre ${bounds.x_min} e ${bounds.x_max} m.`);
  }
  if (!Number.isFinite(y) || y < bounds.y_min || y > bounds.y_max) {
    throw new Error(`Y deve estar entre ${bounds.y_min} e ${bounds.y_max} m.`);
  }
  if (!Number.isFinite(doseRateMSvH) || doseRateMSvH <= 0) {
    throw new Error("A taxa de dose a 1 metro deve ser maior que zero.");
  }
  if (doseRateMSvH > maximumSourceRateMSvH) {
    throw new Error("A taxa máxima é 10 Sv/h (10.000 mSv/h).");
  }
  return {
    x_m: x,
    y_m: y,
    dose_rate_at_1m_uSv_h: (
      doseRateMSvH * microSievertsPerMilliSievert
    ),
  };
}

function isUsbTest() {
  return state.scenario?.detectors?.some(d => d.source_type === "radiacode_jsonl");
}

async function startSimulation() {
  if (isUsbTest()) return;
  let setup;
  try {
    setup = validateSetup();
  } catch (error) {
    setMessage(error.message, true);
    return;
  }
  const button = $("start-button");
  button.disabled = true;
  setMessage("Iniciando a simulação...");
  state.pressedKeys.clear();
  state.lastCommand = null;
  try {
    const response = await api("/simulation/start", {
      method: "POST",
      body: JSON.stringify(setup),
    });
    state.missionId = response.mission_id;
    state.configuredSource = response.source;
    state.missionState = response.state;
    acceptPose(fallbackPose(), true);
    state.radiation = null;
    state.mapped = [];
    state.map = null;
    state.viewBox = null;
    state.accumulatedDose = 0;
    button.textContent = "Reiniciar mapeamento";
    $("map-mode").textContent = "Aguardando primeira medição";
    updateReadings();
    setMessage("Simulação ativa. Use as setas para mover o Go2.");
    scheduleRender();
  } catch (error) {
    setMessage(`Não foi possível iniciar: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function currentCommand() {
  const forward = state.pressedKeys.has("ArrowUp") ? 1 : 0;
  const reverse = state.pressedKeys.has("ArrowDown") ? 1 : 0;
  const left = state.pressedKeys.has("ArrowLeft") ? 1 : 0;
  const right = state.pressedKeys.has("ArrowRight") ? 1 : 0;
  return {
    linear_m_s: (forward - reverse) * 0.45,
    yaw_rate_rad_s: (left - right) * 0.9,
  };
}

async function sendCurrentCommand(force = false) {
  if (state.missionState !== "RUNNING") return;
  const command = currentCommand();
  const signature = `${command.linear_m_s}:${command.yaw_rate_rad_s}`;
  if (!force && signature === state.lastCommand) return;
  state.lastCommand = signature;
  try {
    await api("/mission/control", {
      method: "POST",
      body: JSON.stringify(command),
    });
  } catch (error) {
    state.lastCommand = null;
    setMessage(`Controle indisponível: ${error.message}`, true);
  }
}

function stopRobot() {
  if (!state.pressedKeys.size) return;
  state.pressedKeys.clear();
  void sendCurrentCommand();
}

function bindKeyboard() {
  const arrowKeys = new Set([
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
  ]);
  window.addEventListener("keydown", (event) => {
    if (!arrowKeys.has(event.key) || event.target instanceof HTMLInputElement) return;
    event.preventDefault();
    state.pressedKeys.add(event.key);
    void sendCurrentCommand();
  });
  window.addEventListener("keyup", (event) => {
    if (!arrowKeys.has(event.key) || event.target instanceof HTMLInputElement) return;
    event.preventDefault();
    state.pressedKeys.delete(event.key);
    void sendCurrentCommand();
  });
  window.addEventListener("blur", stopRobot);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopRobot();
  });
  // Reenvia o comando de velocidade enquanto a tecla fica pressionada. O Go2
  // para sozinho se o Move não for renovado (watchdog do serviço de esporte),
  // então mantemos ~10 Hz enquanto houver tecla ativa. Ao soltar, o keyup já
  // envia 0,0 (StopMove) e este laço fica ocioso.
  setInterval(() => {
    if (state.pressedKeys.size > 0) void sendCurrentCommand(true);
  }, 100);
}

function nearestIndex(values, target) {
  if (!Array.isArray(values) || !values.length) return -1;
  let bestIndex = 0;
  let bestDistance = Infinity;
  values.forEach((value, index) => {
    const distance = Math.abs(Number(value) - target);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function mapValueAt(x, y) {
  const payload = state.map;
  if (!payload?.grid_shape || !payload.values_row_major) return null;
  const [rows, columns] = payload.grid_shape.map(Number);
  const column = nearestIndex(payload.x_coordinates_m, x);
  const row = nearestIndex(payload.y_coordinates_m, y);
  if (column < 0 || row < 0 || row >= rows || column >= columns) return null;
  const value = payload.values_row_major[row * columns + column];
  return value == null || !Number.isFinite(Number(value)) ? null : Number(value);
}

function bindMapPointer() {
  const tooltip = $("map-tooltip");
  const stage = canvas.parentElement;
  canvas.addEventListener("pointermove", (event) => {
    const plot = state.plotGeometry;
    if (!plot) return;
    const bounds = canvas.getBoundingClientRect();
    const pixelX = event.clientX - bounds.left;
    const pixelY = event.clientY - bounds.top;
    if (
      pixelX < plot.left
      || pixelX > plot.right
      || pixelY < plot.top
      || pixelY > plot.bottom
    ) {
      tooltip.hidden = true;
      $("map-coordinate").innerHTML = "x — &nbsp; y —";
      return;
    }
    const x = plot.pixelToX(pixelX);
    const y = plot.pixelToY(pixelY);
    const value = mapValueAt(x, y);
    $("map-coordinate").textContent = (
      `x ${formatNumber(x, 2)} m   y ${formatNumber(y, 2)} m`
    );
    tooltip.innerHTML = (
      `x ${formatNumber(x, 2)} m<br>`
      + `y ${formatNumber(y, 2)} m<br>`
      + (
        value == null
          ? "Sem estimativa neste ponto"
          : (
            `<b>${formatRateWithUnit(excessRateUSvH(value))} acima do fundo</b>`
            + `<br>Total: ${formatRateWithUnit(value)}`
            + `<br>${regulatoryBandForExcessRate(excessRateUSvH(value))}`
          )
      )
    );
    tooltip.hidden = false;
    const stageBounds = stage.getBoundingClientRect();
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;
    const left = clamp(pixelX + 16, 8, stageBounds.width - tooltipWidth - 8);
    const top = clamp(pixelY + 16, 8, stageBounds.height - tooltipHeight - 8);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  });
  canvas.addEventListener("pointerleave", () => {
    tooltip.hidden = true;
    $("map-coordinate").innerHTML = "x — &nbsp; y —";
  });
}

async function initialise() {
  try {
    state.scenario = await api("/scenario");
    state.configuredSource = initialSourceFromScenario();
    $("source-x").value = Number(state.configuredSource?.x_m ?? 7.5).toFixed(2);
    $("source-y").value = Number(state.configuredSource?.y_m ?? 5.5).toFixed(2);
    $("source-strength").max = String(
      maximumSourceRateUSvH() / microSievertsPerMilliSievert,
    );
    $("source-strength").value = String(
      Number(
        state.configuredSource?.dose_rate_at_1m_uSv_h ?? 10_000,
      ) / microSievertsPerMilliSievert,
    );
    if (isUsbTest()) {
      document.querySelector(".setup-panel").innerHTML = `<div class="section-heading"><p class="kicker">TESTE USB RADIACODE</p><h2>Radiação real · Go2 virtual</h2><p class="section-description">As coordenadas são simuladas. Este mapa testa o software e não representa a distribuição física da radiação.</p><p class="section-description">Taxa convertida provisoriamente: compare com o visor em µSv/h.</p><p>CPS: <b id="usb-cps">—</b></p><p id="usb-age">Aguardando USB</p><button id="start-button" hidden disabled></button><p id="action-message" class="status-message">Leitura iniciada pelo terminal. Use as setas para mover o robô virtual.</p></div>`;
      document.querySelector(".secondary-readings article span").textContent = "Dose integrada no teste";
      document.querySelector(".secondary-readings article:nth-child(2) small").textContent = "sequência de aquisição";
      document.querySelector(".map-heading .kicker").textContent = "POSIÇÃO SIMULADA · SEM VALIDADE ESPACIAL";
      document.querySelector(".public-reference").textContent = "Teste de software · cores relativas";
      setInterval(updateReadings, 1000);
    }
    acceptPose(fallbackPose(), true);
    const status = await api("/status");
    updateStatus(status);
    if (status.state === "RUNNING") {
      $("start-button").textContent = "Reiniciar mapeamento";
    }
    if (status.counts?.mapped) {
      const samples = await api("/samples?kind=mapped&offset=0&limit=5000");
      state.mapped = samples.items || [];
      try {
        updateMap(await api("/map/latest"));
      } catch {
        // A mission may still be waiting for its first one-second window.
      }
    }
    updateReadings();
    scheduleRender();
  } catch (error) {
    setMessage(`Falha ao carregar o software: ${error.message}`, true);
    scheduleRender();
  }
  connectWebSocket();
}

$("start-button").addEventListener("click", () => void startSimulation());
bindKeyboard();
bindMapPointer();

if (window.ResizeObserver) {
  new ResizeObserver(scheduleRender).observe(canvas);
} else {
  window.addEventListener("resize", scheduleRender);
}

window.addEventListener("error", (event) => {
  if (event.message) {
    setMessage(`Falha na interface: ${event.message}`, true);
  }
});

void initialise();
