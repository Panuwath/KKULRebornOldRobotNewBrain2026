import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {describe} = createRequire(import.meta.url)('./zenbo-device-evidence.js');
const now = 20000;
const minimal = {robot_slug:'booky-1', heartbeat_received_at_ms:now - 1000};
const view = (robot=minimal, selected=['booky-1']) => describe([robot], selected, now);
assert.match(view().summary, /booky-1.*1 วินาที/);
assert.equal(view().rows[0][1], 'ยังไม่รายงาน');
assert.equal(view().rows[2][1], 'ยังไม่รายงาน');
assert.equal(view({...minimal, robot_api_ready:false}).rows[2][1], 'รายงานว่าไม่ใช่');
assert.equal(view({...minimal, robot_api_ready:true}).rows[2][1], 'รายงานว่าใช่');
for (const value of ['true', 'false', 1, 0, null, {}])
  assert.equal(view({...minimal, robot_api_ready:value}).rows[2][1], 'ยังไม่รายงาน');
const hash = 'a'.repeat(64);
const full = {...minimal, version_name:'1.9.48', apk_sha256:hash,
  safety_monitor_active:true, safety_monitor:{required_sensor_coverage:false},
  safety_guard:{collision_guard_enabled:true, fall_guard_enabled:false},
  motion:{body_relative:{watchdog_hard_upper_bound:false}}};
assert.equal(view(full).rows[1][1], hash);
assert.equal(view({...full, apk_sha256:'invalid'}).rows[1][1], 'ยังไม่มี SHA256 ที่ถูกต้อง');
assert.deepEqual(view(full).rows.slice(3).map(row=>row[1]),
  ['รายงานว่าใช่','รายงานว่าไม่ใช่','รายงานว่าใช่','รายงานว่าไม่ใช่','รายงานว่าไม่ใช่']);
// Selection changes and expired/missing/future receipts must discard prior evidence.
for (const selected of [[], ['booky-1','other'], ['other']]) assert.equal(view(full,selected).rows.length,0);
for (const received of [0,null,undefined,'19000',now+1,now-10001])
  assert.equal(view({...full,heartbeat_received_at_ms:received}).rows.length,0);
assert.equal(view({...full,heartbeat_received_at_ms:now-10000}).rows.length,8);
assert.equal(describe([], ['booky-1'], now).rows.length,0);
assert.equal(view(minimal).rows[1][1], 'ยังไม่มี SHA256 ที่ถูกต้อง');
console.log('Device evidence tests passed: incomplete reports, strict booleans, artifact, selection and freshness.');
