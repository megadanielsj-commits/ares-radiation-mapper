"use strict";
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const test = require("node:test");
const root = path.resolve(__dirname, "../..");
const robot = fs.existsSync(path.join(root, "integracao-go2"))
  ? path.join(root, "integracao-go2") : path.resolve(root, "../ares-go2-wifi");
const {setup} = require(path.join(robot, "tests/approved_dashboard.test.cjs"));

test("source simulation adapter retains dose and gradient on every actual timer tick", () => {
  const ui = setup();
  ui.run(fs.readFileSync(path.join(__dirname, "adapter.js"), "utf8"));
  ui.sockets[0].readyState = 1;
  ui.run(`applySnapshot({modo:'simulacao',missao:{id:7},robo:{conectado:true},
    radiacao:{conectado:true},fonte_sim:{x:4,y:3,s:8},pose:{x:0,y:0,yaw:0,ts:1},
    leitura:{ts:Date.now()/1000+.5,detector_id:'sim-1',cps:40,dr_usvh:.5,dose_usv:.0123},
    mapa:{missao_id:7,unidade:'µSv/h',cps_por_usvh:80,nx:2,ny:2,res:.5,
      x0:0,y0:0,valores:[[.5,.7],[1,2]]}});`);
  for (let tick=0; tick<8; tick++) {
    ui.intervals.forEach(cb => cb());
    assert.equal(ui.element("dose-total").textContent, "0,0123");
    assert.equal(ui.element("usb-cps").textContent, "40");
  }
  assert.equal(ui.element("integration-mode").textContent, "Radiação simulada · posição simulada");
  assert.equal(ui.run("state.map.values_row_major[3]"), 160);
  ui.run("renderMapNow(10);");
  assert.equal(ui.images.length, 1);
  assert.ok(ui.labels.includes("FONTE") && ui.labels.includes("GO2"));
  assert.equal(ui.element("sim-apply").disabled, true);
});
