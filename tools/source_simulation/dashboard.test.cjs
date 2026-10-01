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
  ui.run(`window.ARES_SIMULATION_MODEL={sensitivity:80,height_m:.25};`);
  ui.run(fs.readFileSync(path.join(__dirname, "field.js"), "utf8"));
  ui.run(fs.readFileSync(path.join(__dirname, "adapter.js"), "utf8"));
  ui.sockets[0].readyState = 1;
  ui.run(`applySnapshot({modo:'simulacao',missao:{id:7},robo:{conectado:true},
    radiacao:{conectado:true},fonte_sim:{x:4,y:3,s:8},pose:{x:0,y:0,yaw:0,ts:1},
    leitura:{ts:Date.now()/1000+.5,detector_id:'sim-1',cps:40,dr_usvh:.5,dose_usv:.0123},
    resultado:{missao_id:7,n:10,p_fonte:1,x_map:4,y_map:3,s_map:8,b_map:.15},
    mapa:{missao_id:7,unidade:'µSv/h',cps_por_usvh:80,nx:2,ny:2,res:.5,
      x0:0,y0:0,valores:[[.5,.7],[1,2]]}});`);
  for (let tick=0; tick<8; tick++) {
    ui.intervals.forEach(cb => cb());
    assert.equal(ui.element("dose-total").textContent, "0,0123");
    assert.equal(ui.element("usb-cps").textContent, "40");
  }
  assert.equal(ui.element("integration-mode").textContent, "Radiação simulada · posição simulada");
  assert.equal(ui.run("sourceDisplay.field.strength"), 8);
  ui.run("renderMapNow(10);");
  assert.equal(ui.images.length, 1);
  assert.ok(ui.labels.includes("FONTE") && ui.labels.includes("GO2"));
  assert.equal(ui.element("sim-apply").disabled, true);
});

test("full field comes from measured estimator output and covers the entire viewport", () => {
  const ui = setup();
  ui.run(`window.ARES_SIMULATION_MODEL={sensitivity:80,height_m:.25};`);
  for (const name of ["field.js", "adapter.js"]) ui.run(fs.readFileSync(path.join(__dirname, name), "utf8"));
  ui.run(`state.missionId=9;integration.snapshot={};
    acceptSourceEstimate({missao_id:9,n:20,p_fonte:1,x_map:4,y_map:3,s_map:8,b_map:.15});`);
  assert.ok(ui.run("estimatedCounts(sourceDisplay.field,4,3)>estimatedCounts(sourceDisplay.field,0,0)"));
  assert.ok(ui.run("Number.isFinite(estimatedCounts(sourceDisplay.field,100,-100))"));
  const before = ui.run("estimatedCounts(sourceDisplay.field,4,3)");
  ui.run(`state.configuredSource={enabled:true,x_m:100,y_m:100,dose_rate_at_1m_uSv_h:999};`);
  assert.equal(ui.run("estimatedCounts(sourceDisplay.field,4,3)"), before);
  ui.run(`drawHeatmap({left:10,top:20,width:500,height:300,bounds:{x_min:-10,x_max:10,y_min:-10,y_max:10}});`);
  assert.deepEqual(ui.images.at(-1).slice(1), [10,20,500,300]);
  ui.run(`handleBackendEvent({tipo:'mapa',dados:{missao_id:9,unidade:'CPS',nx:1,ny:1,x0:0,y0:0,res:.5,valores:[[42]]}});`);
  assert.equal(ui.run("sourceDisplay.field.strength"), 8);
});

test("a new maximum recolors every historic value and invalidates the whole raster", () => {
  const ui = setup();
  ui.run(`window.ARES_SIMULATION_MODEL={sensitivity:80,height_m:.25};`);
  for (const name of ["field.js", "adapter.js"]) ui.run(fs.readFileSync(path.join(__dirname, name), "utf8"));
  ui.run(`state.missionId=7;integration.snapshot={};
    appendSample({ts:1,x:0,y:0,cps:100});
    acceptSourceEstimate({missao_id:7,n:1,p_fonte:null,x_map:4,y_map:3,s_map:8,b_map:.15});
    renderMapNow(10);`);
  const oldColor = ui.run("JSON.stringify(radiationColor(100).rgb)");
  const oldKey = ui.run("sourceDisplay.raster.key");
  assert.equal(ui.run("colorMaximum()"),100);
  ui.run(`appendSample({ts:2,x:4,y:3,cps:10000});renderMapNow(20);`);
  assert.equal(ui.run("colorMaximum()"),10000);
  assert.notEqual(ui.run("JSON.stringify(radiationColor(100).rgb)"),oldColor);
  assert.notEqual(ui.run("sourceDisplay.raster.key"),oldKey);
  assert.equal(ui.run("state.mapped[0].cps"),100);
  assert.equal(ui.run("state.mapped[0].dose_rate_uSv_h_filtered"),100);
  assert.equal(ui.run("integration.sampleCount"),0); // No synthetic measurements added by drawing.
});
