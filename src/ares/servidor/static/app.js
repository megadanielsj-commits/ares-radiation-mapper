"use strict";
/**
 * Painel do ARES: mapa em canvas 2D (medição + estimativa da fonte), lateral
 * de estado/missão e teleop do robô. Sem dependências externas.
 */

// ---------------------------------------------------------------------- estado
const estado = {
  modo: null,
  robo: null,
  radiacao: null,
  missao: null,
  fonte_sim: null,
  pose: null,
  leitura: null,
  resultado: null,
  mapa: null,
  teleop: null,
};

const trajeto = []; // {x, y} recentes, para desenhar o percurso
const LIMITE_TRAJETO = 6000;

const visao = { cx: 0.0, cy: 0.0, escala: 20, iniciada: false }; // px/m

// ---------------------------------------------------------------------- utilidades
function el(id) {
  return document.getElementById(id);
}

function definirTexto(id, texto) {
  const alvo = el(id);
  if (alvo) alvo.textContent = texto;
}

function fmt(valor, casas) {
  if (valor === null || valor === undefined || !Number.isFinite(valor)) return "—";
  return valor.toFixed(casas === undefined ? 2 : casas);
}

// ---------------------------------------------------------------------- escala de cor (aprox. viridis)
const PARADA_VIRIDIS = [
  [0.0, 68, 1, 84],
  [0.2, 65, 68, 135],
  [0.4, 42, 120, 142],
  [0.6, 34, 168, 132],
  [0.8, 122, 209, 81],
  [1.0, 253, 231, 37],
];

function corViridis(t) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 0; i < PARADA_VIRIDIS.length - 1; i++) {
    const [t0, r0, g0, b0] = PARADA_VIRIDIS[i];
    const [t1, r1, g1, b1] = PARADA_VIRIDIS[i + 1];
    if (t >= t0 && t <= t1) {
      const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
      const r = Math.round(r0 + f * (r1 - r0));
      const g = Math.round(g0 + f * (g1 - g0));
      const b = Math.round(b0 + f * (b1 - b0));
      return `rgb(${r},${g},${b})`;
    }
  }
  const ultima = PARADA_VIRIDIS[PARADA_VIRIDIS.length - 1];
  return `rgb(${ultima[1]},${ultima[2]},${ultima[3]})`;
}

// ---------------------------------------------------------------------- conversão mundo <-> tela
const canvasMapa = el("mapa");
const ctx = canvasMapa.getContext("2d");

function mundoParaTela(x, y) {
  const sx = canvasMapa.width / 2 + (x - visao.cx) * visao.escala;
  const sy = canvasMapa.height / 2 - (y - visao.cy) * visao.escala;
  return [sx, sy];
}

function telaParaMundo(sx, sy) {
  const x = visao.cx + (sx - canvasMapa.width / 2) / visao.escala;
  const y = visao.cy - (sy - canvasMapa.height / 2) / visao.escala;
  return [x, y];
}

function posicaoNoCanvas(evt) {
  const rect = canvasMapa.getBoundingClientRect();
  const escalaX = canvasMapa.width / rect.width;
  const escalaY = canvasMapa.height / rect.height;
  return [(evt.clientX - rect.left) * escalaX, (evt.clientY - rect.top) * escalaY];
}

function inicializarVisaoSeNecessario(grade) {
  if (visao.iniciada || !grade) return;
  visao.cx = grade.x0 + (grade.nx * grade.res) / 2;
  visao.cy = grade.y0 + (grade.ny * grade.res) / 2;
  const ladoM = Math.max(grade.nx, grade.ny) * grade.res;
  visao.escala = ladoM > 0 ? canvasMapa.width / (ladoM * 1.05) : 20;
  visao.iniciada = true;
}

// ---------------------------------------------------------------------- desenho
function percentil95(valores) {
  if (valores.length === 0) return 0.3;
  const ordenados = valores.slice().sort((a, b) => a - b);
  const idx = Math.min(ordenados.length - 1, Math.ceil(0.95 * ordenados.length) - 1);
  return Math.max(ordenados[Math.max(0, idx)], 0.3);
}

function desenharGradeMedida(grade) {
  if (!grade) return null;
  const valores = [];
  for (let ix = 0; ix < grade.nx; ix++) {
    for (let iy = 0; iy < grade.ny; iy++) {
      const v = grade.valores[ix][iy];
      if (v !== null) valores.push(v);
    }
  }
  // Escala de cor: máximo = percentil 95 das células medidas (mín. 0); valores
  // acima do topo saturam na cor mais intensa, sem esticar a escala por causa
  // de poucas células muito acima do resto (ex.: perto de uma fonte).
  const vmax = percentil95(valores);
  for (let ix = 0; ix < grade.nx; ix++) {
    for (let iy = 0; iy < grade.ny; iy++) {
      const v = grade.valores[ix][iy];
      if (v === null) continue;
      const [sx0, sy0] = mundoParaTela(grade.x0 + ix * grade.res, grade.y0 + iy * grade.res);
      const [sx1, sy1] = mundoParaTela(
        grade.x0 + (ix + 1) * grade.res,
        grade.y0 + (iy + 1) * grade.res
      );
      ctx.fillStyle = corViridis(Math.min(1, v / vmax));
      ctx.fillRect(Math.min(sx0, sx1), Math.min(sy0, sy1), Math.abs(sx1 - sx0), Math.abs(sy1 - sy0));
    }
  }
  return vmax;
}

function desenharMarginal(resultado) {
  const regiao = resultado && resultado.regiao95;
  const marginal = resultado && resultado.marginal;
  if (!regiao || !marginal) return;
  let vmax = 0;
  for (let ix = 0; ix < regiao.nx; ix++) {
    for (let iy = 0; iy < regiao.ny; iy++) {
      if (marginal[ix][iy] > vmax) vmax = marginal[ix][iy];
    }
  }
  if (vmax <= 0) return;
  for (let ix = 0; ix < regiao.nx; ix++) {
    for (let iy = 0; iy < regiao.ny; iy++) {
      const t = marginal[ix][iy] / vmax;
      if (t < 0.02) continue;
      const [sx0, sy0] = mundoParaTela(regiao.x0 + ix * regiao.res, regiao.y0 + iy * regiao.res);
      const [sx1, sy1] = mundoParaTela(
        regiao.x0 + (ix + 1) * regiao.res,
        regiao.y0 + (iy + 1) * regiao.res
      );
      ctx.fillStyle = `rgba(255,90,90,${Math.min(0.75, t * 0.8)})`;
      ctx.fillRect(Math.min(sx0, sx1), Math.min(sy0, sy1), Math.abs(sx1 - sx0), Math.abs(sy1 - sy0));
    }
  }
}

function desenharRegiao95(resultado) {
  const regiao = resultado && resultado.regiao95;
  if (!regiao) return;
  const mascara = regiao.mascara;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let ix = 0; ix < regiao.nx; ix++) {
    for (let iy = 0; iy < regiao.ny; iy++) {
      if (!mascara[ix][iy]) continue;
      const x0 = regiao.x0 + ix * regiao.res;
      const y0 = regiao.y0 + iy * regiao.res;
      const x1 = x0 + regiao.res;
      const y1 = y0 + regiao.res;
      const vizinhos = [
        [ix - 1, iy, x0, y0, x0, y1], // borda esquerda
        [ix + 1, iy, x1, y0, x1, y1], // borda direita
        [ix, iy - 1, x0, y0, x1, y0], // borda inferior
        [ix, iy + 1, x0, y1, x1, y1], // borda superior
      ];
      for (const [vx, vy, ax, ay, bx, by] of vizinhos) {
        const dentro = vx >= 0 && vx < regiao.nx && vy >= 0 && vy < regiao.ny;
        if (dentro && mascara[vx][vy]) continue;
        const [sax, say] = mundoParaTela(ax, ay);
        const [sbx, sby] = mundoParaTela(bx, by);
        ctx.moveTo(sax, say);
        ctx.lineTo(sbx, sby);
      }
    }
  }
  ctx.stroke();
}

function desenharCruzMap(resultado) {
  if (!resultado || resultado.x_map === null || resultado.x_map === undefined) return;
  const [sx, sy] = mundoParaTela(resultado.x_map, resultado.y_map);
  const braco = 8;
  ctx.strokeStyle = "#facc15";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(sx - braco, sy);
  ctx.lineTo(sx + braco, sy);
  ctx.moveTo(sx, sy - braco);
  ctx.lineTo(sx, sy + braco);
  ctx.stroke();
}

function desenharTrajeto() {
  if (trajeto.length < 2) return;
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < trajeto.length; i++) {
    const [sx, sy] = mundoParaTela(trajeto[i].x, trajeto[i].y);
    if (i === 0) ctx.moveTo(sx, sy);
    else ctx.lineTo(sx, sy);
  }
  ctx.stroke();
}

// robô: retângulo orientado 0,70 (comprimento, eixo x) x 0,31 m (largura, eixo y)
const ROBO_COMPRIMENTO_M = 0.70;
const ROBO_LARGURA_M = 0.31;

function desenharRobo(pose) {
  if (!pose) return;
  const meioC = ROBO_COMPRIMENTO_M / 2;
  const meioL = ROBO_LARGURA_M / 2;
  const cantosRobo = [
    [meioC, meioL],
    [meioC, -meioL],
    [-meioC, -meioL],
    [-meioC, meioL],
  ];
  const cos = Math.cos(pose.yaw);
  const sin = Math.sin(pose.yaw);
  const pontosTela = cantosRobo.map(([lx, ly]) => {
    const wx = pose.x + lx * cos - ly * sin;
    const wy = pose.y + lx * sin + ly * cos;
    return mundoParaTela(wx, wy);
  });
  ctx.fillStyle = "#f4f4f5";
  ctx.strokeStyle = "#111827";
  ctx.lineWidth = 1;
  ctx.beginPath();
  pontosTela.forEach(([sx, sy], i) => (i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy)));
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // indicador de frente (nariz)
  const nariz = mundoParaTela(pose.x + meioC * 1.4 * cos, pose.y + meioC * 1.4 * sin);
  const centro = mundoParaTela(pose.x, pose.y);
  ctx.strokeStyle = "#ef4444";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(centro[0], centro[1]);
  ctx.lineTo(nariz[0], nariz[1]);
  ctx.stroke();
}

function desenharFonteReal() {
  if (estado.modo !== "simulacao" || !estado.fonte_sim) return;
  const [sx, sy] = mundoParaTela(estado.fonte_sim.x, estado.fonte_sim.y);
  ctx.fillStyle = "#fb7185";
  ctx.strokeStyle = "#7f1d1d";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(sx, sy, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function atualizarLegenda(vmax) {
  const gCtx = el("legenda-gradiente").getContext("2d");
  const largura = gCtx.canvas.width;
  const altura = gCtx.canvas.height;
  const grad = gCtx.createLinearGradient(0, 0, largura, 0);
  for (let i = 0; i <= 10; i++) {
    grad.addColorStop(i / 10, corViridis(i / 10));
  }
  gCtx.fillStyle = grad;
  gCtx.fillRect(0, 0, largura, altura);
  definirTexto("legenda-min", "0");
  definirTexto("legenda-max", vmax === null ? "—" : `≥ ${fmt(vmax, 2)}`);
}

function desenharMapa() {
  ctx.fillStyle = "#0b1020";
  ctx.fillRect(0, 0, canvasMapa.width, canvasMapa.height);

  inicializarVisaoSeNecessario(estado.mapa || (estado.resultado && estado.resultado.regiao95));

  const vmax = desenharGradeMedida(estado.mapa);
  desenharMarginal(estado.resultado);
  desenharRegiao95(estado.resultado);
  desenharCruzMap(estado.resultado);
  desenharTrajeto();
  desenharFonteReal();
  desenharRobo(estado.pose);
  atualizarLegenda(vmax);
}

// ---------------------------------------------------------------------- zoom e arraste
let arrastando = false;
let ultimoArrasto = null;
let inicioClique = null;

canvasMapa.addEventListener("wheel", (evt) => {
  evt.preventDefault();
  const [sx, sy] = posicaoNoCanvas(evt);
  const [wx, wy] = telaParaMundo(sx, sy);
  const fator = evt.deltaY < 0 ? 1.15 : 1 / 1.15;
  visao.escala = Math.max(2, Math.min(400, visao.escala * fator));
  const [wx2, wy2] = telaParaMundo(sx, sy);
  visao.cx += wx - wx2;
  visao.cy += wy - wy2;
  desenharMapa();
}, { passive: false });

canvasMapa.addEventListener("mousedown", (evt) => {
  arrastando = true;
  ultimoArrasto = posicaoNoCanvas(evt);
  inicioClique = { pos: ultimoArrasto, shift: evt.shiftKey };
});

window.addEventListener("mousemove", (evt) => {
  if (!arrastando) return;
  const atual = posicaoNoCanvas(evt);
  const dx = atual[0] - ultimoArrasto[0];
  const dy = atual[1] - ultimoArrasto[1];
  if (Math.abs(dx) > 0 || Math.abs(dy) > 0) {
    visao.cx -= dx / visao.escala;
    visao.cy += dy / visao.escala;
    ultimoArrasto = atual;
    desenharMapa();
  }
});

window.addEventListener("mouseup", (evt) => {
  if (!arrastando) return;
  arrastando = false;
  if (!inicioClique) return;
  const fim = posicaoNoCanvas(evt);
  const distancia = Math.hypot(fim[0] - inicioClique.pos[0], fim[1] - inicioClique.pos[1]);
  if (distancia < 4 && inicioClique.shift && estado.modo === "simulacao") {
    const [wx, wy] = telaParaMundo(fim[0], fim[1]);
    const s = parseFloat(el("fonte-s").value) || 2.0;
    fetch("/api/simulacao/fonte", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ x: wx, y: wy, s: s }),
    }).catch(() => {});
  }
  inicioClique = null;
});

// ---------------------------------------------------------------------- pílulas de estado
function atualizarPilula(id, ok, texto, tituloErro) {
  const pilula = el(id);
  if (!pilula) return;
  pilula.classList.toggle("ok", ok === true);
  pilula.classList.toggle("erro", ok === false);
  pilula.querySelector(".txt").textContent = texto;
  pilula.title = tituloErro || "sem erro";
}

function atualizarCabecalho() {
  atualizarPilula("pill-modo", null, estado.modo || "—", "modo da aplicação");
  const robo = estado.robo || {};
  atualizarPilula("pill-go2", !!robo.conectado, robo.conectado ? "Go2 ok" : "Go2 offline", robo.erro);
  const rad = estado.radiacao || {};
  atualizarPilula(
    "pill-fs5000",
    !!rad.conectado,
    rad.conectado ? "FS-5000 ok" : "FS-5000 offline",
    rad.erro
  );
}

function atualizarPilulaWs(conectado) {
  atualizarPilula("pill-ws", conectado, conectado ? "WS ok" : "WS caído", conectado ? null : "sem conexão com o servidor");
}

// ---------------------------------------------------------------------- lateral: leitura e estimativa
function atualizarLeitura() {
  const l = estado.leitura;
  definirTexto("v-dr", l ? `${fmt(l.dr_usvh, 3)} µSv/h` : "—");
  definirTexto("v-cps", l ? String(l.cps) : "—");
  definirTexto("v-dose", l ? `${fmt(l.dose_usv, 3)} µSv` : "—");
}

function atualizarEstimativa() {
  const r = estado.resultado;
  if (!r) {
    definirTexto("v-pfonte", "—");
    definirTexto("v-posicao", "—");
    definirTexto("v-s", "—");
    definirTexto("v-n", "—");
    el("avisos").replaceChildren();
    return;
  }
  definirTexto(
    "v-pfonte",
    r.p_fonte === null ? "cobertura insuficiente" : `${fmt(r.p_fonte * 100, 1)} %`
  );
  definirTexto(
    "v-posicao",
    r.x_media === null
      ? "—"
      : `(${fmt(r.x_media, 2)}, ${fmt(r.y_media, 2)}) m ± ${fmt(r.desvio_m, 2)} m`
  );
  definirTexto("v-s", r.s_map === null ? "—" : `${fmt(r.s_map, 2)} µSv/h @ 1 m`);
  definirTexto("v-n", `${r.n} (rejeitadas: ${r.rejeitadas})`);

  const avisos = [];
  if (r.s_no_limite) avisos.push("S no limite da grade — intensidade pode estar subestimada/superestimada.");
  if (r.b_no_limite) avisos.push("Fundo (b) no limite da grade.");
  if (r.fonte_na_borda) avisos.push("Posição estimada na borda da área — considere ampliar a cobertura.");
  el("avisos").replaceChildren(
    ...avisos.map((texto) => {
      const div = document.createElement("div");
      div.className = "aviso";
      div.textContent = texto;
      return div;
    })
  );
}

// ---------------------------------------------------------------------- missões
async function carregarMissoes() {
  try {
    const resp = await fetch("/api/missoes");
    const lista = await resp.json();
    renderizarMissoes(lista);
  } catch (e) {
    /* silencioso: lista permanece como estava */
  }
}

function renderizarMissoes(lista) {
  const ul = el("lista-missoes");
  ul.replaceChildren(
    ...lista.map((m) => {
      const li = document.createElement("li");
      const nome = document.createElement("span");
      nome.textContent = `#${m.id} ${m.nome || "(sem nome)"} — ${m.n_amostras} amostras`;
      const links = document.createElement("span");
      links.className = "exportar";
      const csv = document.createElement("a");
      csv.href = `/api/missoes/${m.id}/amostras.csv`;
      csv.textContent = "CSV";
      const json = document.createElement("a");
      json.href = `/api/missoes/${m.id}.json`;
      json.textContent = "JSON";
      links.append(csv, json);
      li.append(nome, links);
      return li;
    })
  );
}

// ---------------------------------------------------------------------- erros de ação
let temporizadorErroAcao = null;

function mostrarErroAcao(mensagem) {
  const alvo = el("erro-acao");
  alvo.textContent = mensagem;
  alvo.hidden = false;
  if (temporizadorErroAcao) clearTimeout(temporizadorErroAcao);
  temporizadorErroAcao = setTimeout(() => {
    alvo.hidden = true;
  }, 6000);
}

// Em erro (ex.: 409/400), mostra o `detail` do FastAPI (`{"detail": "..."}");
// sem corpo em JSON, cai na mensagem genérica com o status.
async function verificarResposta(resp) {
  if (resp.ok) return true;
  let detalhe = `erro ${resp.status}`;
  try {
    const corpo = await resp.json();
    if (corpo && corpo.detail) detalhe = corpo.detail;
  } catch (e) {
    /* corpo sem JSON: mantém a mensagem genérica */
  }
  mostrarErroAcao(detalhe);
  return false;
}

el("btn-iniciar-missao").addEventListener("click", async () => {
  const nome = el("missao-nome").value.trim();
  const resp = await fetch("/api/missao/iniciar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nome: nome || null }),
  });
  await verificarResposta(resp);
  carregarMissoes();
});

el("btn-encerrar-missao").addEventListener("click", async () => {
  const resp = await fetch("/api/missao/encerrar", { method: "POST" });
  await verificarResposta(resp);
  carregarMissoes();
});

// ---------------------------------------------------------------------- robô: botões
async function acaoRobo(acao) {
  try {
    const resp = await fetch(`/api/robo/${acao}`, { method: "POST" });
    await verificarResposta(resp);
  } catch (e) {
    mostrarErroAcao("falha de rede ao comandar o robô");
  }
}
el("btn-levantar").addEventListener("click", () => acaoRobo("levantar"));
el("btn-deitar").addEventListener("click", () => acaoRobo("deitar"));
el("btn-parar").addEventListener("click", () => {
  pararTeleop();
  acaoRobo("parar");
});

// ---------------------------------------------------------------------- câmera e modo
function atualizarVisibilidadePorModo() {
  el("secao-fonte-sim").hidden = estado.modo !== "simulacao";
  el("secao-camera").hidden = estado.modo !== "real";
}

// Em modo real, a câmera pode não estar disponível ainda (conexão do robô
// em backoff) ou cair no meio do stream; em vez de esconder para sempre,
// tenta de novo a cada 5 s (a seção só fica escondida por causa do modo,
// em `atualizarVisibilidadePorModo`).
const PERIODO_RETENTATIVA_CAMERA_MS = 5000;

el("camera").addEventListener("error", () => {
  if (estado.modo !== "real") return;
  setTimeout(() => {
    el("camera").src = `/camera.mjpg?t=${Date.now()}`;
  }, PERIODO_RETENTATIVA_CAMERA_MS);
});

// ---------------------------------------------------------------------- teleop
// Mapa de teclas -> eixo. Setas/WASD andam e giram; Q/E fazem strafe lateral.
const TECLAS_VX = { ArrowUp: 1, w: 1, W: 1, ArrowDown: -1, s: -1, S: -1 };
const TECLAS_VYAW = { ArrowLeft: 1, a: 1, A: 1, ArrowRight: -1, d: -1, D: -1 };
const TECLAS_VY = { q: 1, Q: 1, e: -1, E: -1 };

const teclasPressionadas = new Set();
let socketComando = null;
let intervaloComando = null;
const PERIODO_COMANDO_MS = 100; // 10 Hz

function velocidadeAtual() {
  let vx = 0, vy = 0, vyaw = 0;
  for (const t of teclasPressionadas) {
    if (t in TECLAS_VX) vx += TECLAS_VX[t];
    if (t in TECLAS_VYAW) vyaw += TECLAS_VYAW[t];
    if (t in TECLAS_VY) vy += TECLAS_VY[t];
  }
  return { vx: Math.sign(vx), vy: Math.sign(vy), vyaw: Math.sign(vyaw) };
}

function enviarComando(v) {
  if (socketComando && socketComando.readyState === WebSocket.OPEN) {
    socketComando.send(JSON.stringify(v));
  }
}

function iniciarEnvioComando() {
  if (intervaloComando) return;
  intervaloComando = setInterval(() => enviarComando(velocidadeAtual()), PERIODO_COMANDO_MS);
}

function pararEnvioComando() {
  if (intervaloComando) {
    clearInterval(intervaloComando);
    intervaloComando = null;
  }
}

function pararTeleop() {
  teclasPressionadas.clear();
  pararEnvioComando();
  enviarComando({ vx: 0, vy: 0, vyaw: 0 });
}

function ehTeclaTeleop(tecla) {
  return tecla in TECLAS_VX || tecla in TECLAS_VYAW || tecla in TECLAS_VY;
}

window.addEventListener("keydown", (evt) => {
  if (evt.target && ["INPUT", "TEXTAREA"].includes(evt.target.tagName)) return;
  if (evt.code === "Space") {
    evt.preventDefault();
    pararTeleop();
    acaoRobo("parar");
    return;
  }
  if (!ehTeclaTeleop(evt.key)) return;
  evt.preventDefault();
  teclasPressionadas.add(evt.key);
  enviarComando(velocidadeAtual());
  iniciarEnvioComando();
});

window.addEventListener("keyup", (evt) => {
  if (!ehTeclaTeleop(evt.key)) return;
  teclasPressionadas.delete(evt.key);
  if (teclasPressionadas.size === 0) {
    pararEnvioComando();
    enviarComando({ vx: 0, vy: 0, vyaw: 0 });
  } else {
    enviarComando(velocidadeAtual());
  }
});

window.addEventListener("blur", pararTeleop);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) pararTeleop();
});

function conectarSocketComando() {
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  socketComando = new WebSocket(`${protocolo}//${location.host}/ws/comando`);
  socketComando.addEventListener("close", () => {
    setTimeout(conectarSocketComando, 1000);
  });
  socketComando.addEventListener("error", () => {
    try { socketComando.close(); } catch (e) { /* ignora */ }
  });
}

// ---------------------------------------------------------------------- WebSocket de eventos
function aplicarEvento(tipo, dados) {
  if (tipo === "snapshot") {
    Object.assign(estado, dados);
    trajeto.length = 0;
    if (estado.pose) trajeto.push({ x: estado.pose.x, y: estado.pose.y });
    atualizarVisibilidadePorModo();
    carregarMissoes();
  } else if (tipo === "pose") {
    estado.pose = dados;
    if (dados) {
      trajeto.push({ x: dados.x, y: dados.y });
      if (trajeto.length > LIMITE_TRAJETO) trajeto.shift();
    }
  } else if (tipo === "leitura") {
    estado.leitura = dados;
  } else if (tipo === "amostra") {
    // usado só para desenhos incrementais futuros; estado agregado vem via "mapa"/"estimativa"
  } else if (tipo === "estimativa") {
    estado.resultado = dados;
  } else if (tipo === "mapa") {
    estado.mapa = dados;
  } else if (tipo === "estado") {
    Object.assign(estado, dados);
    atualizarVisibilidadePorModo();
  }
  atualizarCabecalho();
  atualizarLeitura();
  atualizarEstimativa();
  desenharMapa();
}

function conectarSocketEventos() {
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  const s = new WebSocket(`${protocolo}//${location.host}/ws`);
  s.addEventListener("open", () => atualizarPilulaWs(true));
  s.addEventListener("close", () => {
    atualizarPilulaWs(false);
    setTimeout(conectarSocketEventos, 1000);
  });
  s.addEventListener("error", () => {
    try { s.close(); } catch (e) { /* ignora */ }
  });
  s.addEventListener("message", (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      aplicarEvento(msg.tipo, msg.dados);
    } catch (e) {
      /* mensagem malformada: ignora */
    }
  });
}

// ---------------------------------------------------------------------- início
atualizarPilulaWs(false);
desenharMapa();
conectarSocketEventos();
conectarSocketComando();
