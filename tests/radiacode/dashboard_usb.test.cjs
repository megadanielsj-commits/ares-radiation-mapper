"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("USB dashboard draws the Go2 after replacing the source setup panel", () => {
  const labels = [];
  const drawing = new Proxy({
    measureText: (value) => ({width: value.length * 7}),
    createLinearGradient: () => ({addColorStop() {}}),
    fillText: (value) => labels.push(value),
  }, {
    get(target, property) {
      return property in target ? target[property] : () => {};
    },
  });
  const canvas = {
    clientWidth: 1200,
    clientHeight: 800,
    getContext: () => drawing,
    getBoundingClientRect: () => ({width: 1200, height: 800}),
    addEventListener() {},
    parentElement: {},
  };
  const elements = new Map([
    ["radiation-map", canvas],
    ["start-button", {addEventListener() {}}],
    ["map-tooltip", {}],
  ]);
  // The USB panel replaces the source form and its source-strength input.
  assert.equal(elements.has("source-strength"), false);
  const sandbox = {
    document: {
      getElementById: (id) => elements.get(id) || null,
      addEventListener() {},
    },
    window: {
      devicePixelRatio: 1,
      requestAnimationFrame() {},
      addEventListener() {},
    },
    performance: {now: () => 0},
    setInterval() {},
  };
  vm.createContext(sandbox);
  const source = fs.readFileSync(
    path.resolve(__dirname, "../../src/ares_mapper/web/static/app.js"), "utf8",
  ).replace(/void initialise\(\);\s*$/, "");
  vm.runInContext(source, sandbox);
  vm.runInContext(`
    state.scenario = {
      detectors: [{source_type: "radiacode_jsonl"}],
      world: {bounds_m: {x_min: 0, x_max: 10, y_min: 0, y_max: 8},
              background: {dose_rate_uSv_h: 0.1}},
      trajectory: {start_m: [2, 2, 0.32], yaw_start_rad: 0},
    };
    state.radiation = {dose_rate_uSv_h: 0.12};
    renderMapNow(0);
  `, sandbox);
  assert.ok(labels.includes("GO2"), "the robot must be drawn on the USB map");
});
