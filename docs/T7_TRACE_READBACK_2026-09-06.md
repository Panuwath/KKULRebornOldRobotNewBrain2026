# T7 trace and heartbeat readback — 2026-09-06

Baseline: c8bc095, clean main. Scope: complete readback from gateway history to
LIFF and close the isolated PostgreSQL validation gap. No motion flag changes,
robot commands, APK changes/installations or production schema/config changes.

## Behavior

- Command trace matches existing top-level command_id, relative envelope and
  acknowledgement payloads. Robot scoping remains exact. The response preserves
  latest-receipt fields and adds events in gateway receipt order, capped at the
  newest 100 with an explicit truncation flag. Receipt order is not execution
  order or physical confirmation.
- PostgreSQL command_history.payload_json is TEXT in the existing schema. Cast
  to jsonb for matching; the same query also supports native JSONB. No migration.
- LIFF history has a GET-only expandable command trace. Every event label and
  reason is inserted as text. Artifact/version readback remains available.
- Core publishes heartbeat_received_at_ms from its own receipt clock. Retained
  heartbeat sets it to zero. Other telemetry cannot refresh it. A new heartbeat
  omitting readiness/artifact/safety fields withdraws the old claims.
- The speed deck reads the direct robot capability with this receipt timestamp;
  no last_event fallback. API failures clear the capability shown by the deck.

## Verification

- Reproduced two failing nested-trace regression cases before the fix.
- 194 Core tests pass with each test file in its own process, plus 34 scenario
  subtests. The previously documented combined-process configuration isolation
  problem is outside this patch; tests were not weakened or removed.
- Seven opt-in PostgreSQL tests pass in a disposable UTF-8 local PostgreSQL 17
  cluster: original migration/transaction coverage, trace on TEXT and JSONB,
  and field rollout/session rollback gate roundtrip. No tests ran on production DB.
- Both LIFF Node test files pass; tests cover the API capability shape, missing
  timestamps, future/stale receipt and unrelated telemetry.
- Browser local fixture: history displays four observations; expanding the
  trace shows Gateway -> APK received -> SDK submitted -> SDK stop requested.
  Screenshot inspected. The fixture is explicitly synthetic, GET-only, and
  uses in-memory SQLite; no broker or robot connection exists.
- Production browser login and existing history were readable before deployment.
  Final new-revision readback follows merge and deployment.
- Independent review found retained readiness on incomplete heartbeats; fixed
  by withdrawing heartbeat-owned claims and adding an API regression test.

## Repeat PostgreSQL checks

Use a Python test environment with pytest and psycopg[binary,pool], then run:

```sh
python scripts/test-postgres-local.py --pg-bin /opt/homebrew/opt/postgresql@17/bin
```

The runner creates a fresh UTF-8 cluster on a random loopback port, replaces
inherited DB credentials for the subprocess, runs only the opt-in test file,
stops its server and removes its own temporary files. If stopping fails, it
retains the cluster instead of deleting a running database. It never uses a
production DSN. The pg-bin argument is installation-specific.

## Remaining field work

S5/T8 still need an exact installed safety-enabled APK, on-site operator,
sensors, expiring field permit and physical measurements. Production T9
activation/rollback remains dependent on that evidence. The trace explicitly
reports physical_motion_verified=false. Both relative feature flags stay OFF.
