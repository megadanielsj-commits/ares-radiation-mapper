const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {setup} = require('../../tests/compatibility/map_renderer.test.cjs');
const shell = fs.readFileSync(__dirname+'/static/console.js','utf8');

function scaleUI() {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};
    state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,x_m:4,y_m:3,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};`);
  ui.element('color-scale-mode').value = 'automatic';
  ui.run(shell);
  return ui;
}

function applyManual(ui, blue, blueUnit, red, redUnit) {
  ui.element('color-scale-mode').value = 'manual';
  ui.run('showColorScaleInputs()');
  ui.element('scale-blue').value = String(blue);
  ui.element('scale-blue-unit').value = blueUnit;
  ui.element('scale-red').value = String(red);
  ui.element('scale-red-unit').value = redUnit;
  return ui.run('applyColorScale()');
}

test('manual scale maps unit-aware endpoints with the original logarithmic palette', () => {
  const ui = scaleUI();
  assert.equal(applyManual(ui, 100, 'nSv/h', .01, 'mSv/h'), true);
  assert.equal(ui.run('colorMinimum()'), .1);
  assert.equal(ui.run('colorMaximum()'), 10);
  assert.equal(ui.run('colorFractionForTotalRate(.1)'), 0);
  assert.equal(ui.run('colorFractionForTotalRate(1)'), .5);
  assert.equal(ui.run('colorFractionForTotalRate(10)'), 1);
  assert.equal(ui.run('JSON.stringify(radiationColor(.01).rgb)'), '[11,27,42]');
  assert.equal(ui.run('JSON.stringify(radiationColor(100).rgb)'), '[183,35,58]');
  assert.equal(ui.element('manual-color-scale').hidden, false);
  assert.match(ui.element('color-scale-message').textContent, /azul 100,00 nSv\/h/);
  assert.equal(applyManual(ui, .12651909855776466, 'uSv/h', .00001, 'Sv/h'), true);
  assert.equal(ui.run('colorMinimum()'), .12651909855776466);
  assert.equal(ui.run('colorMaximum()'), 10);
});

test('manual scale stays fixed across telemetry; automatic restores the original live bounds', () => {
  const ui = scaleUI();
  assert.equal(applyManual(ui, .1, 'uSv/h', 10, 'uSv/h'), true);
  ui.run(`state.configuredSource.dose_rate_at_1m_uSv_h=80;
    state.radiation={dose_rate_uSv_h:10000};
    state.mapped=[{dose_rate_uSv_h_filtered:10000}];`);
  assert.equal(ui.run('colorMinimum()'), .1);
  assert.equal(ui.run('colorMaximum()'), 10);
  const expected = ui.run('JSON.stringify([originalColorMinimum(),originalColorMaximum()])');
  ui.element('color-scale-mode').value = 'automatic';
  ui.run('showColorScaleInputs()');
  assert.equal(ui.element('manual-color-scale').hidden, true);
  assert.equal(ui.run('applyColorScale()'), true);
  assert.equal(ui.run('JSON.stringify([colorMinimum(),colorMaximum()])'), expected);
  assert.equal(ui.run('colorMaximum()'), 320.1);
  ui.run('state.configuredSource.dose_rate_at_1m_uSv_h=8');
  assert.equal(ui.run('colorMaximum()'), 32.1);
  const html = fs.readFileSync(__dirname+'/static/index.html','utf8');
  assert.match(html, /value="automatic" selected/);
  assert.match(html, /id="manual-color-scale" hidden/);
});

test('invalid manual bounds preserve the last valid scale and do not invent zero', () => {
  const ui = scaleUI();
  assert.equal(applyManual(ui, .1, 'uSv/h', 10, 'uSv/h'), true);
  for (const [blue, unit, red] of [['','uSv/h',10], [0,'uSv/h',10],
    [-1,'uSv/h',10], ['NaN','uSv/h',10], ['Infinity','uSv/h',10],
    [.1,'unknown',10], [10,'uSv/h',10], [11,'uSv/h',10], [.1,'uSv/h',0]]) {
    assert.equal(applyManual(ui, blue, unit, red, 'uSv/h'), false);
    assert.equal(ui.run('colorMinimum()'), .1);
    assert.equal(ui.run('colorMaximum()'), 10);
    assert.match(ui.element('color-scale-message').textContent, /escala anterior foi mantida/);
  }
});

test('applying a scale repaints every old grid cell and legend without changing numeric data or placement', () => {
  const ui = scaleUI();
  ui.run(`state.map={grid_shape:[2,2],values_row_major:[.1,1,10,null],
      x_coordinates_m:[0,1],y_coordinates_m:[0,1]};
    state.mapped=[{sensor_x_m:2,sensor_y_m:2,dose_rate_uSv_h_filtered:.12651909855776466}];
    state.radiation={dose_rate_uSv_h:.12651909855776466,cps:123.456789,cpm:7407.40734};
    const plot={left:0,right:100,top:0,bottom:100,width:100,height:100,scale:10,
      bounds:{x_min:0,y_max:10},xToPixel:x=>x*10,yToPixel:y=>(10-y)*10};
    const numeric=JSON.stringify([state.map,state.mapped,state.radiation,state.configuredSource]);
    const pathColors=[]; context.fill=()=>pathColors.push(context.fillStyle);
    drawHeatmap(plot); drawMeasuredPath(plot);`);
  const old = Array.from(ui.rasters.at(-1));
  const oldPoint = ui.run('pathColors.at(-1)');
  assert.equal(applyManual(ui, .1, 'uSv/h', 10, 'uSv/h'), true);
  ui.run('drawHeatmap(plot); drawMeasuredPath(plot); drawColorBar(plot)');
  const current = Array.from(ui.rasters.at(-1));
  assert.notDeepEqual(current, old);
  assert.notEqual(ui.run('pathColors.at(-1)'), oldPoint);
  assert.equal(ui.run('pathColors.at(-1)'), ui.run('radiationColor(state.mapped[0].dose_rate_uSv_h_filtered).css'));
  // Renderer flips rows; the absent cell remains transparent, not blue.
  assert.deepEqual(current.slice(0, 4), [183,35,58,238]);
  assert.equal(current[7], 0);
  assert.deepEqual(current.slice(8, 12), [11,27,42,238]);
  assert.deepEqual(ui.images.at(-1).slice(1), ui.images[0].slice(1));
  assert.ok(ui.labels.includes('100,00 nSv/h'));
  assert.ok(ui.labels.includes('10,00 µSv/h'));
  assert.equal(ui.run('JSON.stringify([state.map,state.mapped,state.radiation,state.configuredSource])'), ui.run('numeric'));
  ui.run('state.map=null; drawHeatmap(plot)');
  assert.equal(ui.rasters.length, 2, 'scale creates no map before measurements');
});

test('color-scale controls work independently of source visibility in all four modes', () => {
  const ui = scaleUI();
  for (const mode of ['simulation','robot_simulated_source','usb_simulated_robot','hardware']) {
    ui.run(`consoleSnapshot={mode:'${mode}',inputs:{radiation:'${mode === 'simulation' || mode === 'robot_simulated_source' ? 'simulated' : 'real'}'}}`);
    assert.equal(applyManual(ui, 100, 'nSv/h', 1, 'mSv/h'), true, mode);
    assert.equal(ui.run('colorMinimum()'), .1, mode);
    assert.equal(ui.run('colorMaximum()'), 1000, mode);
    assert.equal(ui.run('sourceMarkerVisible()'), false, mode);
    ui.element('color-scale-mode').value = 'automatic';
    assert.equal(ui.run('applyColorScale()'), true, mode);
  }
});

test('configured robot speed affects full-simulation arrow movement only, including reverse and stop', () => {
  const ui = scaleUI();
  ui.run(`consoleSnapshot={mode:'simulation',setup:{simulated_robot_speed_m_s:1.2}};
    state.pressedKeys.add('ArrowUp'); state.pressedKeys.add('ArrowLeft');`);
  assert.equal(ui.run('currentCommand().linear_m_s'), 1.2);
  assert.equal(ui.run('currentCommand().yaw_rate_rad_s'), .9);
  ui.run(`state.pressedKeys.delete('ArrowUp'); state.pressedKeys.add('ArrowDown');`);
  assert.equal(ui.run('currentCommand().linear_m_s'), -1.2);
  ui.run('state.pressedKeys.clear()');
  assert.equal(ui.run('currentCommand().linear_m_s'), 0);
  for (const mode of ['usb_simulated_robot','robot_simulated_source','hardware']) {
    ui.run(`consoleSnapshot.mode='${mode}'; state.pressedKeys.add('ArrowUp');`);
    assert.equal(ui.run('currentCommand().linear_m_s'), .45, mode);
  }
  ui.element('operation-mode').value = 'hardware';
  ui.run('showModeChoice()');
  assert.equal(ui.element('simulated-robot-speed-row').hidden, true);
  ui.element('operation-mode').value = 'simulation';
  ui.run('showModeChoice()');
  assert.equal(ui.element('simulated-robot-speed-row').hidden, false);
});

test('the shell cannot replace the approved heatmap, palette or robot functions', () => {
  for (const name of ['drawHeatmap','drawGridAndAxes','drawMeasuredPath','drawRobot',
    'radiationColor','radiationStops','colorFractionForTotalRate',
    'viewBounds','renderMapNow','mapValueAt','updateMap','calculatePlotGeometry','resizeCanvas','drawColorBar']) {
    assert.equal(new RegExp(`\\b${name}\\s*=`).test(shell), false, name);
    assert.equal(new RegExp(`function\\s+${name}\\b`).test(shell), false, name);
  }
});

test('a fresh recording hides the active source; revealing it delegates to the approved marker', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};
    document.querySelector=s=>s==='.legend.source'
      ? {parentElement:document.getElementById('source-legend-test')} : document.getElementById(s);
    state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,x_m:4,y_m:3,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};`);
  const source = ui.run('JSON.stringify(state.configuredSource)');
  const marker = ui.run('drawSource.toString()');
  ui.run(shell);
  assert.equal(ui.run('originalSourceMarker.toString()'), marker);
  assert.equal(ui.run('sourceMarkerVisible()'), false);
  assert.equal(ui.element('source-legend-test').hidden, true);
  ui.run('renderMapNow(0)');
  assert.equal(ui.labels.includes('FONTE'), false);
  assert.ok(ui.labels.includes('GO2'));
  assert.equal(ui.rasters.length, 0, 'no heatmap is invented before measurements');
  assert.equal(ui.run('JSON.stringify(state.configuredSource)'), source);
  ui.labels.length = 0;
  ui.element('show-source-marker').checked = true;
  ui.run('syncSourceMarkerLegend(); renderMapNow(0)');
  assert.equal(ui.element('source-legend-test').hidden, false);
  assert.ok(ui.labels.includes('FONTE'));
  assert.equal(ui.run('JSON.stringify(state.configuredSource)'), source);
  ui.labels.length = 0;
  ui.element('show-source-marker').checked = false;
  ui.run('syncSourceMarkerLegend(); renderMapNow(0)');
  assert.equal(ui.labels.includes('FONTE'), false);
  const html = fs.readFileSync(__dirname+'/static/index.html','utf8');
  const control = html.match(/<input[^>]*id="show-source-marker"[^>]*>/)[0];
  assert.equal(/\bchecked\b/.test(control), false);
});

test('source visibility changes no heatmap pixels, readings, coordinates or source settings', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};
    state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,x_m:4,y_m:3,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};
    state.map={grid_shape:[2,2],values_row_major:[1,2,3,4],
      x_coordinates_m:[0,1],y_coordinates_m:[0,1]};
    state.mapped=[{sensor_x_m:2,sensor_y_m:2,dose_rate_uSv_h_filtered:.12651909855776466}];
    state.radiation={dose_rate_uSv_h:.12651909855776466,cps:123.456789};
    const plot={left:0,right:100,top:0,bottom:100,width:100,height:100,scale:10,
      bounds:{x_min:0,y_max:10},xToPixel:x=>x*10,yToPixel:y=>(10-y)*10};
    const numeric=JSON.stringify([state.scenario,state.configuredSource,state.map,state.mapped,state.radiation]);`);
  ui.run(shell);
  ui.run('drawHeatmap(plot); drawSource(plot)');
  const hidden = Array.from(ui.rasters.at(-1));
  ui.element('show-source-marker').checked = true;
  ui.run('drawHeatmap(plot); drawSource(plot)');
  assert.deepEqual(Array.from(ui.rasters.at(-1)), hidden);
  assert.equal(ui.run('JSON.stringify([state.scenario,state.configuredSource,state.map,state.mapped,state.radiation])'), ui.run('numeric'));
  ui.element('show-source-marker').checked = false;
  ui.run('drawHeatmap(plot); drawSource(plot)');
  assert.deepEqual(Array.from(ui.rasters.at(-1)), hidden);
});

test('source reveal is available only with synthetic radiation, across all four modes', () => {
  const ui = setup();
  ui.run(`crypto={randomUUID:()=>'one'}; navigator={sendBeacon(){}};
    document.querySelectorAll=()=>[]; document.addEventListener=()=>{};`);
  ui.run(shell);
  ui.element('show-source-marker').checked = true;
  for (const [mode, expected] of [['simulation',true],['robot_simulated_source',true],
    ['usb_simulated_robot',false],['hardware',false]]) {
    ui.run(`consoleSnapshot={mode:'${mode}'};`);
    assert.equal(ui.run('sourceMarkerVisible()'), expected, mode);
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
