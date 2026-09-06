# Zenbo field test: L13-L20 governance

Use one clear, measured L10 route only. Keep the route to the existing L8
limit: straight forward, 5-15 cm, speed 1, and 1.5-second watchdog. Do not
test this workflow around people, stairs, edges, or moving obstacles.

## Before starting

1. Confirm the Android client is online and reports `SAFETY_SONAR`,
   `SAFETY_DROP_LASER`, and `CALIBRATED_ROUTE` in field-readiness.
2. Test physical speech, emergency stop, sonar and drop/edge sensor separately.
   A successful API response is not proof of any of those behaviours.
3. Keep `AUTONOMOUS_MOTION_ENABLED=false` until those checks pass. The first
   movement trial must have an operator beside the robot and a clear 15 cm path.

## Expected Core/n8n order

1. Certify the exact route version (L12).
2. Create operator authorization and release the route (L13-L14).
3. Record localization and safety-envelope checks (L15-L16).
4. Reserve the exclusive zone (L17), record a fault drill (L19), and create
   an L20 permit.
5. Call `/api/v1/autonomy/preflight`. `permit_blockers` must be empty before
   using the permit; `dispatch_blockers` also becomes empty only after current
   field-attestation and robot heartbeat/readiness are present.
6. Start the route with `operation_permit_id`, then confirm exactly one segment.

## Safety-stop trial

1. Trigger a safe, documented stop condition or use the operator stop command;
   never obstruct wheels or create a fall risk deliberately.
2. Expect `SAFETY_STOPPED`, route state `RECOVERY_REQUIRED`, a critical alert,
   and the old permit state `REVOKED`.
3. The zone must remain reserved while recovery is pending.
4. Physically inspect the route, record a new L7 field attestation, issue a
   new L20 permit, then use the L11 recovery workflow with that new permit.
   Retrying with the old permit must be rejected.

## Completion and cancellation

- A completed or aborted route releases its L17 zone automatically.
- A cancelled recovery also releases the zone.
- An operator may revoke a permit or release a zone through the reviewed n8n
  gateways. Revoking a permit never substitutes for an emergency stop command.

Record the observed robot speech, sensor reaction, face/gesture, motion
distance, Core route state, and time. Report deviations with the route run ID
and the scenario-event timeline; do not include tokens or broker credentials.
