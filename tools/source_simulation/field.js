"use strict";

// Projeção do resultado do estimador existente. Não lê a fonte configurada.
function fieldFromEstimate(result, model) {
  if (!result || !model || !Number.isFinite(result.n) || result.n < 1
      || ![result.x_map, result.y_map, result.s_map, result.b_map,
        model.sensitivity, model.height_m].every(Number.isFinite)
      || result.s_map < 0 || result.b_map < 0
      || model.sensitivity <= 0 || model.height_m <= 0) return null;
  const probability = Number.isFinite(result.p_fonte)
    ? Math.max(0, Math.min(1, result.p_fonte)) : 0;
  return {mission: result.missao_id, n: result.n, x: result.x_map, y: result.y_map,
    strength: probability * result.s_map, background: result.b_map,
    sensitivity: model.sensitivity, height2: model.height_m ** 2,
    partial: !Number.isFinite(result.p_fonte) || !!result.fonte_na_borda
      || !!result.s_no_limite || !!result.b_no_limite};
}

function estimatedCounts(field, x, y) {
  const distance2 = (x - field.x) ** 2 + (y - field.y) ** 2;
  return field.sensitivity * (field.background + field.strength / (distance2 + field.height2));
}

function estimatedPeakCounts(field) {
  return field ? estimatedCounts(field, field.x, field.y) : 0;
}
