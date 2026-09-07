# T8 field readiness readback — 2026-09-07

Baseline main: 6723f33. Add a read-only check beside the bounded coordinate form
using the existing GET robot field-calibration endpoint. Show Thai descriptions
and original blocker codes, check time, and a ten-second validity window.

The reader requires one selected robot, discards responses after a target change,
rejects malformed or contradictory reports, withdraws stale/future results, and
reports authentication/network/offline failures. No background network polling
is added; a local timer expires the displayed snapshot. Concurrent refreshes
coalesce while a request is pending. Blockers render with textContent.

A successful preflight is explicitly not physical calibration, a permit, or
permission to move. The reader does not modify feature flags, issue permits,
publish MQTT, or change motion gating. Core and APK remain OFF.

Validation: all four Node suites pass, including GET-only transport, target
races, stale/future results, malformed reports, unknown blocker codes, and
network/offline errors. Chrome with a synthetic robot shows APK hash, sensor
coverage and watchdog blockers while all motion levels and submit remain OFF.
Production deployment uses existing source backup and prior-image rollback,
then checks source/public hashes and Core health without robot commands.

S5/T8 physical measurements and T9 staged activation/physical rollback still
require the on-site operator and installed APK/sensor/STOP evidence described
in RELATIVE_MOTION_RELEASE_2026-09-06.md. This UI does not complete those gates.
