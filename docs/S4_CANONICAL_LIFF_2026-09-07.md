# S4 canonical relative motion UI — 2026-09-07

Baseline: main e52e31d. User authorized implementation, main merge, and deployment
to https://lib.kku.ac.th/liff/. Core and APK relative flags remain OFF.

## Change

The speed selector previously appeared beside the direction-only hold remote,
while the coordinate form was inside commented-out advanced markup. Its legacy
helper still built a generic motion request with a safety-policy update.

The drive tab now has a separate, collapsed bounded-coordinate form. It defaults
to L1 and clears speed/session/permit inputs when the selected robot changes.
The hold remote remains SDK-managed, direction-only, with no speed selector.

Robot discovery now reports a server-owned relative-motion policy snapshot.
The selector requires Core enablement, a fresh policy snapshot, exactly one
robot, and fresh ready/supported capability. Submission additionally requires
both permit IDs, a valid nonzero bounded motion and policy-compliant speed.
Only the canonical robot relative-motion endpoint is called, with operation and
field permit headers, UUID command/session IDs, increasing sequence and expiry.
Core still independently enforces ownership, artifact, sensor, permit and policy
gates. Client checks cannot authorize motion.

There is one POST per click, no overlapping in-flight submission, no legacy
fallback and no automatic retry. Network failure displays an unknown outcome
and command ID for history lookup. A gateway published receipt explicitly does
not claim physical movement. The latest receipt is separate from readiness so
background polling does not erase an uncertain result.

## Local evidence

- 195 Core tests and 34 scenario subtests pass, running each test file in its own
  process to preserve the existing import/config isolation convention.
- Seven opt-in PostgreSQL integration cases skipped in this run. No DB query,
  schema, database configuration, or Android source changed.
- Three Node suites pass, including actual shipped UI handler execution with a
  fake transport: flag OFF and missing permit produce zero requests, an overlap
  produces no second request, a successful request uses only canonical fields
  and permit headers, and network failure has no retry/fallback.
- Chrome against a local HTTP fixture with synthetic operator and fresh capable
  robot: direction-only remote has no selector; separate coordinate panel shows
  L1 selected, all seven levels disabled and submit disabled while Core is OFF.
  The fixture refuses all POSTs and has no MQTT connection.
- Production preflight: changed runtime files and Compose match baseline hashes;
  online robot count is zero. Full diff reviewed locally and whitespace checked.

## Remaining phases

T6/S4 software integration and T7 evidence readback are implemented behind OFF
flags. S5/T8 require the named on-site operator, installed APK hash, sensor and
STOP checks, and measured trials in field/relative-motion-trials.csv. T9 software
dry-run support exists; staged enablement and physical rollback remain pending
those field gates. Neither this change nor synthetic tests complete calibration.

Deployment must retain the previous Core image and source backup, then verify
main source hashes in the running container, public LIFF asset hashes, health,
robot policy enabled=false, and authenticated browser readback. No motion probe
is part of deployment verification.
