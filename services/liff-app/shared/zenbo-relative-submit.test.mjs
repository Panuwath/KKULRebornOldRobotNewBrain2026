import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const drive = createRequire(import.meta.url)('./zenbo-drive-control.js');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
// Execute the shipped handler with a fake transport; never contact an API or robot.
const handler = html.slice(html.indexOf('    async function sendMotion('), html.indexOf('    function updateHeadVal('));
assert.ok(handler.includes('async function sendMotion'));
function fixture(enabled = true, transport) {
  const calls = [];
  const elements = {
    'relative-motion-status': {textContent: ''},
    'relative-operation-permit': {value: 'operation-1'},
    'relative-field-permit': {value: 'field-1'}
  };
  const now = Date.now();
  let nextId = 0;
  const context = vm.createContext({
    window: {ZenboDriveControl: drive}, document: {getElementById: id => elements[id]},
    crypto: {randomUUID: () => `synthetic-${++nextId}`}, Date,
    API_BASE: '/liff-api', relativeMotionBusy: false, relativeSourceSession: null,
    relativeSourceSequence: 0, selectedRobots: ['synthetic-booky'], requestedMotionSpeed: 1,
    relativeMotionPolicy: {enabled, reported_at_ms: now, max_body_speed_level: 3,
      max_distance_m: 0.15, hard_stop_after_ms: 1500},
    selectedMotionCapability: () => ({supported: true, robot_api_ready: true,
      reported_at_ms: now, policy_max_speed_level: 3}),
    renderMotionSpeedDeck: () => {},
    fetch: async (...args) => { calls.push(args); return transport ? transport() : {
      ok: true, json: async () => ({published: true})}; }
  });
  vm.runInContext(handler, context);
  return {context, calls, elements};
}
const disabled = fixture(false);
await disabled.context.sendMotion(0.1, 0, 0);
assert.equal(disabled.calls.length, 0);
const missingPermit = fixture();
missingPermit.elements['relative-field-permit'].value = '';
await missingPermit.context.sendMotion(0.1, 0, 0);
assert.equal(missingPermit.calls.length, 0);
let release;
const success = fixture(true, () => new Promise(resolve => { release = resolve; }));
const first = success.context.sendMotion(0.1, 0, 0);
await success.context.sendMotion(0.1, 0, 0);
assert.equal(success.calls.length, 1, 'overlapping click must not submit');
release({ok: true, json: async () => ({published: true})});
await first;
const [url, options] = success.calls[0];
assert.equal(url, '/liff-api/api/v1/robots/synthetic-booky/relative-motion');
assert.equal(options.headers['X-Operation-Permit-Id'], 'operation-1');
assert.equal(options.headers['X-Field-Permit-Id'], 'field-1');
const body = JSON.parse(options.body);
assert.equal(body.motion_request.control_mode, 'RELATIVE_BODY');
assert.equal(body.safety, undefined);
assert.equal(body.motion, undefined);
assert.match(success.elements['relative-motion-status'].textContent, /ยังไม่ยืนยัน/);
const failed = fixture(true, () => { throw new Error('synthetic network loss'); });
await failed.context.sendMotion(0.1, 0, 0);
assert.equal(failed.calls.length, 1, 'transport failure must never retry or fall back');
assert.match(failed.elements['relative-motion-status'].textContent, /ไม่ทราบผลการส่ง/);
assert.equal(failed.context.relativeMotionBusy, false);
console.log('Canonical relative UI transport tests passed (synthetic, no network).');
