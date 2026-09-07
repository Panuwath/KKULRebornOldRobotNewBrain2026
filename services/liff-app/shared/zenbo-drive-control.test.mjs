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

// The API receipt timestamp, not another event or a robot-supplied clock, owns freshness.
const apiRobot = {robot_slug: 'booky', robot_api_ready: true, heartbeat_received_at_ms: 9000,
  motion: {body_relative: {supported: true, policy_max_speed_level: 3}},
  last_event: {received_at_ms: 10000, data: {motion: {body_relative: {supported: true}}}}};
assert.deepEqual(drive.capabilityFromRobot(apiRobot), {
  supported: true, robot_api_ready: true, reported_at_ms: 9000, policy_max_speed_level: 3});
assert.equal(drive.capabilityFromRobot(null), null);
assert.equal(drive.deriveState({robotSelected: true, nowMs: 20001,
  capability: drive.capabilityFromRobot(apiRobot)}).reason, 'STALE_HEARTBEAT');
assert.equal(drive.deriveState({robotSelected: true, nowMs: 10000,
  capability: drive.capabilityFromRobot({...apiRobot, heartbeat_received_at_ms: undefined})}).enabled, false);

const submissionOptions = {
  robotSlugs: ['booky-1'], capability: freshCapability, nowMs: 10000,
  corePolicy: {enabled: true, reported_at_ms: 10000, max_body_speed_level: 3,
    max_distance_m: 0.15, hard_stop_after_ms: 1500},
  operationPermitId: 'operation-1', fieldPermitId: 'field-1',
  commandId: 'command-1', sourceSessionId: 'session-1', sourceSeq: 1,
  requestedLevel: 2, xMeters: 0.1, yMeters: 0, thetaDegrees: 0
};
const canonical = drive.prepareRelativeSubmission(submissionOptions);
assert.equal(canonical.path, '/api/v1/robots/booky-1/relative-motion');
assert.equal(canonical.headers['X-Field-Permit-Id'], 'field-1');
assert.equal(canonical.headers['X-Operation-Permit-Id'], 'operation-1');
assert.equal(canonical.body.motion_request.requested_speed_level, 2);
assert.equal(canonical.body.expires_at_ms, 11500);
assert.equal(canonical.body.safety, undefined);
assert.equal(canonical.body.motion, undefined);
for (const [change, reason] of [
  [{corePolicy: {...submissionOptions.corePolicy, enabled: false}}, 'RELATIVE_MOTION_DISABLED'],
  [{robotSlugs: ['one','two']}, 'SINGLE_ROBOT_REQUIRED'],
  [{fieldPermitId: ''}, 'FIELD_PERMIT_REQUIRED'],
  [{operationPermitId: ''}, 'OPERATION_PERMIT_REQUIRED'],
  [{nowMs: 21001}, 'STALE_CORE_POLICY'],
  [{requestedLevel: 4}, 'SPEED_EXCEEDS_POLICY'],
  [{xMeters: 0.16}, 'DISTANCE_EXCEEDS_POLICY'],
  [{thetaDegrees: 361}, 'INVALID_MOTION'],
]) assert.throws(() => drive.prepareRelativeSubmission({...submissionOptions,...change}), new RegExp(reason));

assert.equal(drive.deriveState({mode: 'remote', featureEnabled: false}).reason, 'SDK_DIRECTION_ONLY');
assert.equal(drive.deriveState({featureEnabled: true, policyFresh: false}).reason, 'STALE_CORE_POLICY');
