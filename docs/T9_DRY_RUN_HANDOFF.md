# T9 software rehearsal

Scope: durable L1-L3 session transitions and Core preview gating. No field
calibration, motion enablement, APK installation, or deployment is performed.

## Offline rehearsal

Run `python3 services/core-api/field_rollout_drill.py` from the repository root.
The separate process forces SQLite `:memory:` before importing the adapter,
creates a synthetic operator and permit, advances L1-L3, rolls back, and proves
the old session cannot authorize another preview. It neither imports the main
application nor constructs a broker client. Its evidence is synthetic only.

## Recovering a lost response

Open `/liff/rollout/` and enter the robot slug. GET `/{robot_slug}/rollout-drills/active`
under `/api/v1/robots` finds the caller-owned open session (admins can read any).
It works after permit expiry/revocation so the session can still be closed.
Read closed sessions by their known ID. Never retry a mutation without readback.

## API workflow

Authenticated operator routes under `/api/v1/robots/{robot_slug}/rollout-drills`:

1. `POST` with `{"permit_id":"..."}` creates `LOCKED` and returns session ID/revision.
2. `POST /{session_id}/advance` with `{"revision":0}` advances one level. Use the
   revision returned by each response for the next step. Maximum is L3.
3. `GET /{session_id}` returns persisted state and transition history.
4. `POST /{session_id}/rollback` with the latest revision closes the session.
   Repeating rollback after closure returns the terminal result.

Relative-motion dry-run additionally requires `X-Rollout-Session-Id`,
`X-Field-Permit-Id`, and the existing `X-Operation-Permit-Id` headers.
The session must belong to the operator/robot/permit and have reached the
requested level. All existing feature, heartbeat, artifact, calibration and
motion-policy gates still apply. A session alone cannot make these pass.

Only one nonterminal session exists per robot. Concurrent requests serialize
with database locks and revision checks. Permit revocation serializes against
permit validation. Expired or revoked permits prevent advancement and preview;
the operator or an admin can still close the session. A new session may be
created after closure if a matching permit remains valid.

Rollback scope is **this rehearsal session**. It does not revoke all robot
permits, switch runtime flags, withdraw APK capabilities, stop physical motion,
or restore an APK. Historical `SIMULATED_L*` state is not current readiness.
Preview authorization is a snapshot, not a transferable execution permit.

## Database and release boundary

SQLite schema is initialized by the existing adapter; PostgreSQL uses
`0009_field_rollout_sessions.sql`. Validate the PostgreSQL migration and
multiworker concurrency in an isolated PostgreSQL instance before deploying
there. The local SQLite tests do not establish PostgreSQL runtime parity.

Physical release still needs supervised T8 evidence, verified production STOP behavior, installed safety-enabled APK, trusted heartbeat
transport, and artifact/session/policy binding. The controller integration is now compiled behind an OFF flag; deployed APK
readiness still requires a fresh readback. Default builds report relative motion
unsupported and no physical hard watchdog guarantee, so field gates remain closed.
See `RELATIVE_MOTION_RELEASE_2026-09-06.md` for field preparation and evidence status.
