"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function setup() {
  const labels = [], elements = new Map(), listeners = {}, sockets = [], intervals = [], images = [];
  const drawing = new Proxy({measureText: text => ({width: text.length * 7}),
    createLinearGradient: () => ({addColorStop() {}}), fillText: text => labels.push(text),
    drawImage: (...args) => images.push(args)},
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
    document: {getElementById: element, querySelector: element,
      createElement: () => ({getContext: () => ({createImageData: (w,h) => ({data: new Uint8ClampedArray(w*h*4)}), putImageData() {}})}),
      addEventListener(name, callback) {listeners[name] = callback;}},
    window: {devicePixelRatio: 1, requestAnimationFrame() {}, setInterval(cb) {intervals.push(cb);}, setTimeout() {},
      addEventListener(name, callback) {listeners[name] = callback;}}, performance: {now: () => 0}};
  vm.createContext(sandbox);
  for (const file of ["renderer.js", "integration.js"]) {
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, "../src/ares/servidor/static/approved", file), "utf8"), sandbox);
  }
  return {run: code => vm.runInContext(code, sandbox), labels, element, sockets, listeners, intervals, images};
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

test("interpolated grid draws a gradient with correct axis order, units and world position", () => {
  const ui = setup();
  ui.run(`state.missionId=7; integration.snapshot={};
    handleBackendEvent({tipo:'mapa',dados:{missao_id:7,unidade:'CPS',nx:2,ny:3,
      x0:10,y0:20,res:.5,valores:[[1,2,null],[4,5,6]]}});`);
  assert.equal(ui.run("JSON.stringify(state.map.values_row_major)"), "[1,4,2,5,null,6]");
  assert.equal(ui.run("JSON.stringify(state.map.grid_shape)"), "[3,2]");
  ui.run(`drawHeatmap({left:0,top:0,width:100,height:100,scale:10,bounds:{x_min:0,y_max:30},
    xToPixel:x=>x*10,yToPixel:y=>(30-y)*10});`);
  assert.equal(ui.images.length, 1);
  assert.deepEqual(ui.images[0].slice(1), [100,85,10,15]);
  ui.run(`handleBackendEvent({tipo:'estado',dados:{missao:{id:7},robo:{conectado:false},radiacao:{conectado:false}}});`);
  assert.ok(ui.run("state.map")); // Status updates do not erase a completed map event.
  ui.run(`acceptMeasuredMap({missao_id:7,unidade:'µSv/h',cps_por_usvh:80,nx:1,ny:1,
    x0:0,y0:0,res:1,valores:[[.5]]});`);
  assert.equal(ui.run("state.map.values_row_major[0]"), 40);
  ui.run(`handleBackendEvent({tipo:'mapa',dados:{missao_id:6,unidade:'CPS',nx:1,ny:1,
    x0:0,y0:0,res:1,valores:[[999]]}});`);
  assert.equal(ui.run("state.map.values_row_major[0]"), 40);
});

test("timer follows the current reading renderer and never blanks a supplied simulated dose", () => {
  const ui = setup();
  ui.sockets[0].readyState=1;
  ui.run(`integration.snapshot={radiacao:{conectado:true}};
    state.radiation={ts:Date.now()/1000+.5001,detector_id:'sim-1',cps:30,dr_usvh:.375,dose_usv:.0123};
    updateReadings();`);
  assert.equal(ui.element('dose-total').textContent,'0,0123');
  assert.equal(ui.element('usb-cps').textContent,'30');
  ui.run(`const priorReadings=updateReadings; updateReadings=()=>{priorReadings(); document.getElementById('called').textContent='yes';};`);
  for (let tick=0; tick<8; tick++) {
    ui.intervals.forEach(cb=>cb());
    assert.equal(ui.element('dose-total').textContent,'0,0123');
    assert.equal(ui.element('called').textContent,'yes');
  }
});

module.exports = {setup};
