# Relative motion release — 2026-09-06

## Contract

Deliver the T5 bounded-only decision through T6/S4 integration, T7 traceability,
T8/S5 field preparation and T9 rehearsal. Merge reviewed software to main and
publish Core/LIFF to https://lib.kku.ac.th/liff/. Never substitute SDK submission
for physical velocity or stopping proof. No continuous velocity API, reflection,
repeated moveBody loop, database engine switch or automatic level sequence.
Baseline: 0934206; clean main before work. Production source and Compose were
compared byte-for-byte with that baseline. Production already selects pgsql;
this release preserves its database configuration and schema.

## Implementation and remaining gates

| Phase | Software | Physical/release acceptance |
| --- | --- | --- |
| T6 / S4 | Public moveBody L1–L7 adapter, OFF BuildConfig flag, monotonic deadline, no overlapping relative commands, cancellation on disconnect/STOP | Installed safety-enabled APK and measured stop behavior still required |
| T7 | APK_RECEIVED, SDK_SUBMITTED, REJECTED, SDK_STOP_REQUESTED correlated by command_id; artifact/history readback; live heartbeat freshness | SDK_SUBMITTED is a submission, not SDK callback or physical proof |
| S5 / T8 | Preflight and expiring field permits already exist; blank measurement sheet supplied | BLOCKED pending named on-site operator, exact installed hash, sensors, permit and physical measurements |
| T9 | Durable L1–L3 synthetic session/rollback drill | Production staged enablement and physical rollback drill remain blocked by T8 |

Core RELATIVE_MOTION_ENABLED defaults false. Android RELATIVE_MOTION_ENABLED is
compiled false in every variant. Heartbeat continues to advertise no hard-stop
physical guarantee. This is an OFF release, not permission to activate motion.

## Field procedure

Use [relative-motion-trials.csv](field/relative-motion-trials.csv); all 84 rows
are unmeasured placeholders, not results. Record exact source SHA, version and
installed base APK SHA256, robot slug, operator, safety observer, permit expiry,
floor conditions, measurement instrument/timebase and an evidence file per trial.
No automated sequence is supplied. Move one explicit bounded step at a time,
starting L1; initial translation must not exceed 0.15 m. Choose a separate bounded
turn angle with the operator. Record left/right angular velocity separately;
linear velocity may be inapplicable for turns.

Before each step check fresh non-retained heartbeat (<=10 seconds), RobotAPI,
unique MQTT client, safety policy epoch, collision/fall sensor coverage, local
hard limit, exact artifact, current permit and physical emergency STOP access.
Do not enable production to bypass preflight. A safety-enabled test build must
be installed and reviewed before field work. A software watchdog requests STOP;
Android scheduling and SDK behavior still need physical measurement.

Measure every direction at each allowed level. Record onset, requested stop,
physical stop, stopping distance, overshoot, and independent observed velocity.
Three trials per cell are feasibility smoke evidence only: report n, maximum,
failures and every raw result; do not claim a reliable p95 from three trials.
A failed stop, sensor, overlap, reconnect/resume or telemetry check ends the
session and blocks all higher levels. L6/L7 require explicit expiring permission.

## Rollout and rollback

After accepted physical evidence: internal L1–L3, then separately reviewed L4–L5,
then per-level attestation for L6–L7. Keep the current installed artifact pinned;
monitor correlated ACK mismatch, rejection, stale heartbeat and measured stop
latency. Enabling flags is a separate field action with operator present.

On any failure: physical/operator STOP first, close/revoke permits, disable Core
and APK relative flags, confirm fresh capability withdrawal, restore the exact
previously verified APK and repeat sensor/STOP checks. Core OFF prevents new
relative dispatch but does not stop an already moving robot. Session rollback
only closes the synthetic drill and does not execute these physical actions.

For this web release deploy.sh creates a source backup before syncing and rebuilds
only Core. Preserve that backup and previous image for rollback; retain current
DB and secrets. Do not replay motion while checking HTTP, history or assets.

## Verification ledger

- Core: 189 tests pass when each test file runs in its own process; 34 scenario
  subtests pass. Five opt-in PostgreSQL integration tests were skipped (no local
  PostgreSQL test service). No database schema or backend configuration changed.
- The combined-process suite exposed four import/configuration
  isolation failures; isolated scenario execution passes all 40 tests.
- Android: 18 unit tests pass; :app:assembleDebug succeeds using JDK 17.
- LIFF: both existing Node test files pass; future heartbeat/type regressions added.
- T9 synthetic drill: SIMULATED_L1 -> L2 -> L3 -> ROLLED_BACK; subsequent preview
  blocked; MQTT publish attempted=false, physical authorized=false.
- Independent review findings fixed: legacy/relative ownership, deadline scheduling
  failure STOP, correlated terminal ACK, and policy cancellation of legacy motion.
- deploy.sh dry-run passes. Its local tests now explicitly select isolated SQLite
  so they cannot inherit the deployment host's PostgreSQL configuration.
- Chrome visual verification is blocked by an open extension UI; HTTP and deployed
  file hashes will be checked separately. This is not a browser rendering PASS.

Local Android debug build is a compile/test artifact only; it is not uploaded,
installed or attested for field use. Merge/deployment evidence is reported with
the final GitHub revision after release.
