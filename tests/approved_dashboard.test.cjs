"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function setup() {
  const labels = [], elements = new Map(), listeners = {}, sockets = [];
  const drawing = new Proxy({measureText: text => ({width: text.length * 7}),
    createLinearGradient: () => ({addColorStop() {}}), fillText: text => labels.push(text)},
    {get: (obj, key) => obj[key] || (() => {})});
  const canvas = {clientWidth: 1200, clientHeight: 800, getContext: () => drawing,
    getBoundingClientRect: () => ({width: 1200, height: 800}), parentElement: {}};
  elements.set("radiation-map", canvas);
  function element(id) {
    if (!elements.has(id)) elements.set(id, {style: {}, addEventListener() {}, classList: {toggle() {}}});
    return elements.get(id);
  }
  class Socket {
    static OPEN = 1; static CONNECTING = 0;
    constructor(url) { this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(text) { this.sent.push(JSON.parse(text)); }
    close() { this.readyState = 3; }
  }
  const sandbox = {console, Date, HTMLInputElement: class {}, HTMLTextAreaElement: class {},
    fetch: () => new Promise(() => {}), WebSocket: Socket, location: {protocol: "http:", host: "localhost:8001"},
    document: {getElementById: element, querySelector: element, addEventListener(name, callback) {listeners[name] = callback;}},
    window: {devicePixelRatio: 1, requestAnimationFrame() {}, setInterval() {}, setTimeout() {},
      addEventListener(name, callback) {listeners[name] = callback;}}, performance: {now: () => 0}};
  vm.createContext(sandbox);
  for (const file of ["renderer.js", "integration.js"]) {
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../src/ares/servidor/static/approved", file), "utf8"), sandbox);
  }
  return {run: code => vm.runInContext(code, sandbox), labels, element, sockets, listeners};
}

test("approved Go2 drawing survives the WebRTC boundary and no robot is invented", () => {
  const ui = setup();
  ui.run(`renderMapNow(0);`);
  assert.equal(ui.labels.includes("GO2"), false);
  ui.run(`integration.snapshot = {robo: {conectado: true}};
    handleBackendEvent({tipo: "pose", dados: {ts: 10, x: 2, y: 3, yaw: 0}});
    renderMapNow(100);`);
  assert.ok(ui.labels.includes("GO2"));
  assert.equal(ui.run("state.pose.ts"), 10);
});

test("events retain original timestamps, counts and synchronized position across status updates", () => {
  const ui = setup();
  ui.run(`state.missionId = 7;
    applySnapshot({modo: "simulacao", robo: {conectado: true}, radiacao: {conectado: true},
      missao: {id: 7}, pose: {ts: 1, x: 0, y: 0, yaw: 0}, leitura: {ts: 1, cps: 1}});
    handleBackendEvent({tipo: "pose", dados: {ts: 20, x: 4, y: 5, yaw: .2}});
    handleBackendEvent({tipo: "leitura", dados: {ts: 21, cps: 23, dr_usvh: null}});
    handleBackendEvent({tipo: "amostra", dados: {ts: 21, x: 3.8, y: 4.9, cps: 23}});
    handleBackendEvent({tipo: "amostra", dados: {ts: 21, x: 3.8, y: 4.9, cps: 23}});
    handleBackendEvent({tipo: "estado", dados: {missao: {id: 7}, robo: {conectado: true}, radiacao: {conectado: true}}});`);
  assert.equal(ui.run("state.pose.ts"), 20);
  assert.equal(ui.run("state.radiation.ts"), 21);
  assert.equal(ui.run("state.mapped.length"), 1);
  assert.equal(ui.element("sample-count").textContent, "1");
  assert.equal(ui.run("state.mapped[0].sensor_x_m"), 3.8);
  assert.equal(ui.run("state.mapped[0].dose_rate_uSv_h_filtered"), 23);
  assert.equal(ui.element("dose-total").textContent, "—");
});

test("teleop uses native commands, stops on blur and does not replay a held key after reconnect", () => {
  const ui = setup();
  const telemetry = ui.sockets[0]; telemetry.readyState = 1; telemetry.onopen();
  const commands = ui.sockets[1]; commands.readyState = 1; commands.onopen();
  ui.run(`state.missionState = "RUNNING"; integration.snapshot = {robo: {conectado: true}};`);
  ui.listeners.keydown({key: "ArrowUp", target: {}, preventDefault() {}});
  assert.equal(commands.sent.at(-1).vx, .45);
  ui.listeners.blur();
  assert.deepEqual(commands.sent.at(-1), {vx: 0, vy: 0, vyaw: 0});
  ui.listeners.keydown({key: "ArrowUp", target: {}, preventDefault() {}});
  commands.onclose();
  assert.equal(ui.run("state.pressedKeys.size"), 0);
  commands.onopen();
  assert.equal(commands.sent.at(-1).vx, 0);
});

test("USB disconnect and stale timestamps never appear as fresh readings", () => {
  const ui = setup();
  ui.sockets[0].readyState = 1;
  ui.run(`integration.snapshot = {radiacao: {conectado: true}};
    state.radiation = {ts: Date.now()/1000 - 4, cps: 20, dr_usvh: .12}; updateReadings();`);
  assert.equal(ui.element("usb-cps").textContent, "—");
  ui.run(`applySnapshot({robo: {conectado: false}, radiacao: {conectado: false}});`);
  assert.equal(ui.run("state.radiation"), null);
  assert.equal(ui.run("state.pose"), null);
});
