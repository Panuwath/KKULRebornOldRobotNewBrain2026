import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import driveControlModule from './zenbo-drive-control.js';

const drive = driveControlModule;
const golden = JSON.parse(readFileSync(new URL('../../../contracts/relative_motion_golden.json', import.meta.url)));
const freshCapability = {
  supported: true,
  robot_api_ready: true,
  reported_at_ms: 9_000,
  policy_max_speed_level: 4
};

assert.deepEqual(drive.LEVELS, [1, 2, 3, 4, 5, 6, 7]);

const goldenRequest = golden.valid.request;
assert.deepEqual(drive.createMotionRequest({
  commandId: goldenRequest.command_id,
  sourceSessionId: goldenRequest.source_session_id,
  sourceSeq: goldenRequest.source_seq,
  issuedAtMs: goldenRequest.issued_at_ms,
  expiresAtMs: goldenRequest.expires_at_ms,
  xMeters: goldenRequest.motion_request.x_m,
  yMeters: goldenRequest.motion_request.y_m,
  thetaDegrees: goldenRequest.motion_request.theta_deg,
  requestedLevel: goldenRequest.motion_request.requested_speed_level,
  policy: { max_body_speed_level: 7 }
}), goldenRequest);

const defaultModel = drive.createModel({
  mode: 'relative',
  robotSelected: true,
  capability: freshCapability,
  nowMs: 10_000
});
assert.equal(defaultModel.requestedLevel, 1);
assert.equal(defaultModel.levels.length, 7);
assert.equal(defaultModel.levels[0].selected, true);
assert.equal(defaultModel.levels[3].disabled, false);
assert.equal(defaultModel.levels[4].disabled, true);
assert.equal(defaultModel.levels[4].reason, 'เกิน policy cap L4');

let selections = 0;
assert.equal(drive.selectLevel(defaultModel, 3, () => { selections += 1; }), true);
assert.equal(defaultModel.requestedLevel, 3);
assert.equal(selections, 1);
assert.equal(drive.selectLevel(defaultModel, 7, () => { selections += 1; }), false);
assert.equal(selections, 1);

const remoteModel = drive.createModel({ mode: 'remote', robotSelected: true });
assert.equal(remoteModel.levels.every(level => level.disabled), true);
assert.equal(remoteModel.state.reason, 'SDK_DIRECTION_ONLY');

const noRobot = drive.createModel({ mode: 'relative', robotSelected: false });
assert.equal(noRobot.state.reason, 'NO_ROBOT');
assert.equal(noRobot.levels.every(level => level.disabled), true);

const missing = drive.createModel({ mode: 'relative', robotSelected: true });
assert.equal(missing.state.reason, 'CAPABILITY_MISSING');

const stale = drive.createModel({
  mode: 'relative',
  robotSelected: true,
  capability: freshCapability,
  nowMs: 20_001,
  staleAfterMs: 10_000
});
assert.equal(stale.state.reason, 'STALE_HEARTBEAT');
assert.equal(stale.levels.every(level => level.disabled), true);

const moving = drive.createModel({
  mode: 'relative',
  robotSelected: true,
  capability: freshCapability,
  nowMs: 10_000,
  moving: true
});
assert.equal(moving.levels.every(level => level.disabled), true);
assert.equal(moving.levels[0].reason, drive.reasonText('MOVING'));

let networkWrites = 0;
globalThis.fetch = async () => {
  networkWrites += 1;
  throw new Error('selection must not use network');
};
const selectable = drive.createModel({
  mode: 'relative',
  robotSelected: true,
  capability: { ...freshCapability, policy_max_speed_level: 7 },
  nowMs: 10_000
});
for (let level = 1; level <= 7; level += 1) {
  assert.equal(drive.selectLevel(selectable, level), true);
}
assert.equal(networkWrites, 0);

console.log('Zenbo drive control tests passed');

assert.equal(drive.deriveState({robotSelected: true, nowMs: 10000,
  capability: {...freshCapability, reported_at_ms: 11000}}).reason, 'STALE_HEARTBEAT');
assert.equal(drive.deriveState({robotSelected: true, nowMs: 10000,
  capability: {...freshCapability, supported: 'false'}}).enabled, false);
