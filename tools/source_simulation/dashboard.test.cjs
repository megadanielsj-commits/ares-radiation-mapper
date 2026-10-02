'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function setup() {
  const elements = new Map(), rasters = [], images = [], labels = [];
  const drawing = new Proxy({measureText:t=>({width:t.length*7}),
    createLinearGradient:()=>({addColorStop(){}}),
    fillText:t=>labels.push(t), drawImage:(...args)=>images.push(args)},
    {get:(obj,key)=>obj[key] || (()=>{})});
  const canvas = {clientWidth:1200, clientHeight:800,getContext:()=>drawing,
    getBoundingClientRect:()=>({width:1200,height:800}),addEventListener(){},parentElement:{}};
  elements.set('radiation-map',canvas);
  function element(id) {
    if (!elements.has(id)) elements.set(id,{value:'10',max:'10000',style:{},
      addEventListener(){},classList:{toggle(){}}});
    return elements.get(id);
  }
  const sandbox={console,Date,HTMLInputElement:class {},performance:{now:()=>0},
    fetch:()=>new Promise(()=>{}),setInterval(){},
    document:{getElementById:element,querySelector:element,addEventListener(){},
      createElement:()=>({getContext:()=>({
        createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),
        putImageData:image=>rasters.push(image.data)})})},
    window:{devicePixelRatio:1,requestAnimationFrame(){},addEventListener(){},setTimeout(){},
      location:{protocol:'http:',host:'localhost:8001'}}};
  vm.createContext(sandbox);
  const script=fs.readFileSync(path.resolve(__dirname,'../../src/ares_mapper/web/static/app.js'),'utf8');
  vm.runInContext(script,sandbox);
  return {run:code=>vm.runInContext(code,sandbox),images,rasters,labels,element};
}

test('a higher reading does not change the original mission scale or reinterpret old points',()=>{
  const ui=setup();
  ui.run(`state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,x_m:4,y_m:3,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};
    state.mapped=[{sensor_x_m:2,sensor_y_m:2,dose_rate_uSv_h_filtered:1}];`);
  const color=ui.run('JSON.stringify(radiationColor(1).rgb)'), maximum=ui.run('colorMaximum()');
  ui.run(`state.mapped.push({sensor_x_m:4,sensor_y_m:3,dose_rate_uSv_h_filtered:10000});
    state.radiation={dose_rate_uSv_h:10000};`);
  assert.equal(ui.run('colorMaximum()'),maximum);
  assert.equal(ui.run('JSON.stringify(radiationColor(1).rgb)'),color);
  assert.equal(ui.run('state.mapped[0].dose_rate_uSv_h_filtered'),1);
});

test('the original grid is placed at its world coordinates rather than stretched by auto-zoom',()=>{
  const ui=setup();
  ui.run(`state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};
    state.map={grid_shape:[2,2],values_row_major:[1,2,3,null],
      x_coordinates_m:[0,10],y_coordinates_m:[0,8]};
    drawHeatmap({left:10,top:20,width:400,height:320,scale:10,
      bounds:{x_min:-10,y_max:20},xToPixel:x=>10+(x+10)*10,yToPixel:y=>20+(20-y)*10});`);
  assert.deepEqual(ui.images[0].slice(1),[110,140,100,80]);
  assert.equal(ui.rasters[0][3],238);
  assert.equal(ui.rasters[0][7],0);
  ui.run(`drawHeatmap({left:10,top:20,width:800,height:640,scale:20,
      bounds:{x_min:-10,y_max:20},xToPixel:x=>10+(x+10)*20,yToPixel:y=>20+(20-y)*20});`);
  assert.deepEqual(ui.images[1].slice(1),[210,260,200,160]);
});

test('every map redraw recalculates pixels from numeric values using the shared original palette',()=>{
  const ui=setup();
  ui.run(`state.scenario={detectors:[{source_type:'simulated'}]};
    state.configuredSource={enabled:true,dose_rate_at_1m_uSv_h:8,background_uSv_h:.1};
    state.map={grid_shape:[2,2],values_row_major:[1,2,3,4],
      x_coordinates_m:[0,1],y_coordinates_m:[0,1]};
    const plot={left:0,top:0,width:10,height:10,scale:10,bounds:{x_min:0,y_max:1},
      xToPixel:x=>x*10,yToPixel:y=>(1-y)*10}; drawHeatmap(plot);`);
  const old=Array.from(ui.rasters[0]);
  ui.run('state.configuredSource.dose_rate_at_1m_uSv_h=80; drawHeatmap(plot);');
  assert.notDeepEqual(Array.from(ui.rasters[1]),old);
  assert.equal(ui.run('JSON.stringify(state.map.values_row_major)'),'[1,2,3,4]');
});

module.exports = {setup};
