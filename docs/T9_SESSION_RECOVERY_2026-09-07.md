# T9 session recovery and LIFF rehearsal — 2026-09-07

Baseline main b2616ad. A lost response from session creation left the operator
without the ID required for readback, while a second creation returned
ACTIVE_SESSION_EXISTS. Add GET /api/v1/robots/{robot_slug}/rollout-drills/active
before the session-ID route. It returns the caller-owned open session, or null;
admins can read any open session for that robot. The single SELECT returns a
consistent snapshot with no writes or permit renewal. Revoked/expired permits
do not hide sessions needed for cleanup. Closed sessions remain readable by ID.

The LIFF /liff/rollout/ page supports active recovery, read by ID, explicit session
creation, one-stage advance, and session rollback. Mutations use the latest
returned revision and the existing authenticated Core routes. Busy submissions
are suppressed; network/errors or malformed responses lock further mutations
until successful readback. A ten-second request timeout also enters this
uncertain state; aborting HTTP does not cancel a server-side mutation. Responses from an old robot selection are discarded.
No automatic retry, motion endpoint, MQTT client or actuator is introduced.

A session is software rehearsal only. Rollback closes that session; it does not
STOP the robot, revoke permits, disable flags or restore APKs. The page labels
this boundary explicitly. Server roles, ownership, permit expiry/cap, revision
and terminal-state rules remain authoritative. Reading a session is not fresh
physical readiness. Core and APK relative flags remain OFF.

Validation:
- 197 Core tests and 34 scenario subtests pass with one process per test file.
- Eight PostgreSQL integration tests pass on a disposable UTF-8 loopback cluster,
  including owner/admin recovery after revocation and no active session after
  rollback. No tests use the production DB; no schema/config migration added.
- All six Node suites pass, including revision binding, lost-response recovery,
  no retry while uncertain, malformed physical-authorization claims, target
  races, concurrent click suppression and terminal-session controls.
- Chrome local fixture runs the actual rollout repository against SQLite memory
  with a synthetic operator and permit, without importing main or MQTT. Recovery
  -> SIMULATED_L1 -> L2 -> L3 -> ROLLED_BACK and subsequent new session work;
  advancing past L3 is disabled. Screenshot reviewed.

Production release checks use hash comparison, health and GET-only browser
readback. No production rehearsal mutations or robot commands are part of QA.
S5/T8 measurements and T9 physical activation/rollback remain pending operator,
installed artifact and sensor/STOP evidence.
