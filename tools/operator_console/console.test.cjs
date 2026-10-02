const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {setup} = require('../source_simulation/dashboard.test.cjs');
const shell = fs.readFileSync(__dirname+'/static/console.js','utf8');

test('the new shell cannot replace map or palette functions', () => {
  for (const name of ['drawHeatmap','drawGridAndAxes','drawMeasuredPath','drawSource','drawRobot',
    'radiationColor','radiationStops','colorFractionForTotalRate','colorMaximum','colorMinimum',
    'viewBounds','renderMapNow','mapValueAt','updateMap','calculatePlotGeometry','resizeCanvas','drawColorBar']) {
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
  assert.ok(html.includes('id="global-brake-button"'));
  assert.ok(html.includes('id="physical-ack"'));
  assert.ok(html.includes('ares-logo.png'));
  assert.ok(html.includes('<dialog id="config-dialog"'));
  assert.ok(html.includes('id="expand-map"'));
  assert.equal(html.includes('data-direction='), false);
  assert.equal(html.includes('class="control-panel"'), false);
});

test('real dose samples do not double-count the server mission dose anchor', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`consoleSnapshot={inputs:{radiation:'real'}};
    state.accumulatedDose=.01; state.radiation={dose_rate_uSv_h:.22};
    handleEnvelope({type:'mapped_sample',payload:{dose_rate_uSv_h_filtered:.22,cps:100,
      sensor_x_m:0,sensor_y_m:0,integration_time_s:1}});`);
  assert.equal(ui.run('state.accumulatedDose'), .01);
  assert.equal(ui.run('state.mapped[0].dose_rate_uSv_h_filtered'), .22);
  assert.equal(ui.run('formatRateWithUnit(.22)'), '220,00 nSv/h');
  assert.equal(ui.run('regulatoryBandForExcessRate(.22)'), 'Taxa reportada · conversão USB provisória');
});

test('measurement labels have two decimals without rounding stored dose or rates', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`state.radiation={dose_rate_uSv_h:.224567};
    state.accumulatedDose=.017654; updateReadings();`);
  assert.equal(ui.element('dose-rate').textContent, '224,57');
  assert.equal(ui.element('dose-rate-unit').textContent, 'nSv/h');
  assert.equal(ui.element('dose-total').textContent, '17,65');
  assert.equal(ui.element('dose-total-unit').textContent, 'nSv');
  assert.equal(ui.run('formatRateWithUnit(10456)'), '10,46 mSv/h');
  assert.equal(ui.run('formatRateWithUnit(.12)'), '120,00 nSv/h');
  assert.equal(ui.run('formatRateWithUnit(0)'), '0,00 µSv/h');
  assert.equal(ui.run('formatRateWithUnit(NaN)'), '—');
  assert.equal(ui.run('formatRateWithUnit(null)'), '—');
  assert.equal(ui.run('formatRateWithUnit(.00000123456789)'), '1,23 pSv/h');
  assert.equal(ui.run('formatAxisValue(5, 1)'), '5,00');
  assert.equal(ui.run('state.radiation.dose_rate_uSv_h'), .224567);
  assert.equal(ui.run('state.accumulatedDose'), .017654);
  assert.equal(ui.run('setupNumber(3.5)'), '3.50');
  assert.equal(ui.run('setupNumber(.000001)'), '0.000001');
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

test('positioned mission total is independent of the 5000 point drawing buffer and stale snapshots', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`state.missionId='mission-one';
    acceptPositionedCount('mission-one', 6001);
    state.mapped=new Array(5000).fill({dose_rate_uSv_h_filtered:1});
    updateReadings();
    acceptPositionedCount('mission-one', 6000);`);
  assert.equal(ui.element('sample-count').textContent, '6001');
  ui.run(`handleEnvelope({type:'mapped_sample',payload:{mission_id:'mission-one',
    mapped_sequence:6002,dose_rate_uSv_h_filtered:1,integration_time_s:1}});`);
  assert.equal(ui.element('sample-count').textContent, '6002');
  assert.equal(ui.run('state.mapped.length'), 5000);
  ui.run(`state.missionId='mission-two'; state.map=null;
    acceptPositionedCount('mission-two', 0); updateReadings();
    handleEnvelope({type:'mapped_sample',payload:{mission_id:'mission-one',mapped_sequence:7000}});`);
  assert.equal(ui.element('sample-count').textContent, '0');
});

test('a positive small mission dose stays visible and stored values keep full precision', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.run(`state.accumulatedDose=.000035144194043823516;
    state.radiation={dose_rate_uSv_h:.12651909855776466}; updateReadings();`);
  assert.equal(ui.element('dose-total').textContent, '35,14');
  assert.equal(ui.element('dose-total-unit').textContent, 'pSv');
  assert.equal(ui.element('dose-rate').textContent, '126,52');
  assert.equal(ui.element('dose-rate-unit').textContent, 'nSv/h');
  assert.equal(ui.run('state.accumulatedDose'), .000035144194043823516);
  assert.equal(ui.run('state.radiation.dose_rate_uSv_h'), .12651909855776466);
});

test('SI prefixes cover small and large dose labels without changing map data or colors', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};
    state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};
    state.map={values_row_major:[.12651909855776466,1000,1000000,null]};`);
  const original = ui.run('JSON.stringify([state.map.values_row_major, [.1,1,8,32].map(x=>radiationColor(x).rgb)])');
  ui.run(shell);
  for (const [value, expected] of [[1e-12,'1,00 aSv/h'], [1e-9,'1,00 fSv/h'],
    [1e-6,'1,00 pSv/h'], [.001,'1,00 nSv/h'], [1,'1,00 µSv/h'],
    [1000,'1,00 mSv/h'], [1000000,'1,00 Sv/h'], [10000000,'10,00 Sv/h']]) {
    assert.equal(ui.run(`formatRateWithUnit(${value})`), expected);
  }
  assert.equal(ui.run('formatRateWithUnit(1e-20)'), '0,0000000100 aSv/h');
  assert.equal(ui.run('JSON.stringify([state.map.values_row_major, [.1,1,8,32].map(x=>radiationColor(x).rgb)])'), original);
});
