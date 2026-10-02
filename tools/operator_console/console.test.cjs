const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {setup} = require('../source_simulation/dashboard.test.cjs');
const shell = fs.readFileSync(__dirname+'/static/console.js','utf8');

test('the new shell cannot replace map or palette functions', () => {
  for (const name of ['drawHeatmap','drawGridAndAxes','drawMeasuredPath','drawSource','drawRobot',
    'radiationColor','radiationStops','colorFractionForTotalRate','colorMaximum','colorMinimum',
    'viewBounds','renderMapNow','mapValueAt','updateMap']) {
    assert.equal(new RegExp(`\\b${name}\\s*=`).test(shell), false, name);
    assert.equal(new RegExp(`function\\s+${name}\\b`).test(shell), false, name);
  }
});

test('gradient remains numerically unchanged with the new console shell', () => {
  const ui = setup();
  ui.run(`state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};`);
  const before = ui.run('JSON.stringify([.1,1,8,32].map(x=>radiationColor(x).rgb))');
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  assert.equal(ui.run('JSON.stringify([.1,1,8,32].map(x=>radiationColor(x).rgb))'), before);
});

test('operator shell exposes four distinct inputs and an always available stop', () => {
  const html = fs.readFileSync(__dirname+'/static/index.html','utf8');
  for (const mode of ['simulation','usb_simulated_robot','robot_simulated_source','hardware']) {
    assert.ok(html.includes(`value="${mode}"`));
  }
  assert.ok(html.includes('id="brake-button"'));
  assert.ok(html.includes('id="physical-ack"'));
  assert.ok(html.includes('ares-logo.png'));
});

test('real count samples never turn CPS into cumulative dose', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`consoleSnapshot={inputs:{radiation:'real'}};
    state.accumulatedDose=.01; state.radiation={dose_rate_uSv_h:.22};
    handleEnvelope({type:'mapped_sample',payload:{dose_rate_uSv_h_filtered:100,
      sensor_x_m:0,sensor_y_m:0,integration_time_s:1}});`);
  assert.equal(ui.run('state.accumulatedDose'), .01);
  assert.equal(ui.run('state.mapped[0].dose_rate_uSv_h_filtered'), 100);
  assert.equal(ui.run('formatRateWithUnit(100)'), '100,0 CPS');
  assert.equal(ui.run('regulatoryBandForExcessRate(100)'), 'Contagens · sem conversão CPS para dose');
});

test('missing real dose is displayed as unavailable instead of CPS labeled as dose', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`consoleSnapshot={inputs:{radiation:'real'}};
    state.radiation={dose_rate_uSv_h:null,cps:100};
    state.mapped=[{dose_rate_uSv_h_filtered:100}]; updateReadings();`);
  assert.equal(ui.element('dose-rate').textContent, '—');
});
