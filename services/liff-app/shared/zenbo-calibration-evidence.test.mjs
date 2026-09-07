import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const api=createRequire(import.meta.url)('./zenbo-calibration-evidence.js');
assert.equal(api.template(),readFileSync(new URL('../../../docs/field/relative-motion-trials.csv',import.meta.url),'utf8'));
assert.equal(api.parse(api.template()).length,85);
const blank=api.review(api.template(),1);
assert.equal(blank.status,'INCOMPLETE');assert.equal(blank.completeRows,0);assert.equal(blank.expectedRows,12);
assert.equal(api.review(api.template(),7).expectedRows,84);
assert.deepEqual(api.parse('\uFEFFa,b\r\n"one, two","a""b\nnext"\r\n'),[['a','b'],['one, two','a"b\nnext']]);
assert.throws(()=>api.parse('a\n"unfinished'),/CSV/);
assert.throws(()=>api.parse('a\n"closed"tail'),/CSV/);
assert.throws(()=>api.review('level,level\n1,1'),/ซ้ำ/);
assert.throws(()=>api.review('level\n1'),/ขาดคอลัมน์/);
function filled() {
  return api.parse(api.template()).slice(1).filter(row=>row[0]==='1').map((values,index)=>{
    const row=Object.fromEntries(api.columns.map((key,i)=>[key,values[i]]));
    Object.assign(row,{command_id:'synthetic-'+index,apk_sha256:'a'.repeat(64),source_sha:'b'.repeat(40),robot_slug:'synthetic',operator:'synthetic operator',observer:'synthetic observer',permit_id:'synthetic permit',instrument:'synthetic instrument',timebase:'synthetic common clock',floor_conditions:'synthetic floor',evidence_path:'synthetic/trial-'+index,issued_at_ms:'1000',apk_received_at_ms:'1001',sdk_submitted_at_ms:'1002',physical_onset_at_ms:'1003',stop_requested_at_ms:'1004',physical_stop_at_ms:'1005',stop_distance_m:'0.01',overshoot_m:'0.01',angular_stop_distance_deg:'1',angular_overshoot_deg:'1',velocity_m_s:'0.1',angular_velocity_deg_s:'1',sensor_ok:'true',no_overlap:'true',no_resume:'true',result:'PASS'});
    return row;
  });
}
const csv=rows=>[api.columns.join(','),...rows.map(row=>api.columns.map(key=>row[key]).join(','))].join('\n');
const good=api.review(csv(filled()));
assert.equal(good.status,'READY_FOR_HUMAN_REVIEW');assert.equal(good.completeRows,12);
assert.equal(good.physicalVerified,false);assert.equal(good.motionAuthorized,false);
assert.equal(good.maxRecordedStopLatencyMs,1);
for(const [change,code] of [
  [{physical_stop_at_ms:'1000'},'TIMESTAMP_ORDER'],
  [{physical_stop_at_ms:'Infinity'},'INVALID_TIMESTAMPS'],
  [{stop_distance_m:'-1'},'MEASUREMENT_REQUIRED'],
  [{sensor_ok:'false'},'SAFETY_FAILURE'],
  [{apk_sha256:'bad'},'INVALID_APK_HASH'],
  [{velocity_m_s:''},'MEASURED_SPEED_REQUIRED'],
  [{robot_slug:'different'},'MIXED_ROBOT_OR_ARTIFACT'],
]) {const rows=filled();Object.assign(rows[0],change);const r=api.review(csv(rows));assert.equal(r.status,'INCOMPLETE');assert.ok(r.issues.some(i=>i.code.startsWith(code)),code);}
const turn=filled();turn[6].angular_velocity_deg_s='';assert.ok(api.review(csv(turn)).issues.some(i=>i.code.includes('angular_velocity_deg_s')));
const failure=filled();failure[0].result='FAIL';assert.equal(api.review(csv(failure)).status,'RECORDED_FAILURES');
const duplicate=filled();duplicate[1].command_id=duplicate[0].command_id;assert.ok(api.review(csv(duplicate)).issues.some(i=>i.code==='DUPLICATE_COMMAND'));
const repeated=filled();repeated.push(repeated[0]);assert.ok(api.review(csv(repeated)).issues.some(i=>i.code==='DUPLICATE_TRIAL'));
assert.ok(api.review(csv(filled().slice(1))).issues.some(i=>i.code.startsWith('MISSING_TRIAL')));
console.log('Calibration evidence tests passed: synthetic data only; no motion authorization.');
