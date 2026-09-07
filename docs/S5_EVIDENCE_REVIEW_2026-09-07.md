# S5/T8 calibration file review — 2026-09-07

Baseline: main e1a9a44. The new /liff/calibration/ page reviews CSV locally in
the browser. It never uploads file contents, issues permits, sends robot
commands, or changes flags. A link appears beside field readiness in LIFF.

Download the blank 84-row template (7 levels × 4 directions × 3 trials). Select
the review scope L1 through the chosen maximum; default L1 needs 12 trial rows.
This is a data scope, not authorization to test higher levels. Only rows within
the selected levels contribute to completeness/failure statistics; malformed
CSV structure or trial identifiers are rejected across the file.

The template adds robot_slug, source_sha, observer, instrument, timebase,
floor_conditions and angular measurements. Existing measurement values are not
invented. The old template lacks these columns and is rejected with the missing
column list; copy measured records into the new schema and supply real evidence.
The committed blank CSV is tested against the page-generated template.

Record positive speed magnitudes in velocity_m_s for translation and
angular_velocity_deg_s for turns. Translation requires stop_distance_m and
overshoot_m; turns require angular_stop_distance_deg and angular_overshoot_deg.
Zero stopping distance or overshoot is permitted. All six timestamps must be
positive integer milliseconds expressed on a documented common timebase, in
issue → receive → SDK submission → physical onset → stop request → physical stop
order. Failed/aborted trials may be incomplete; keep them as FAIL and preserve
raw evidence for human review rather than fabricating missing observations.

The validator checks required metadata, full Git/APK hashes, duplicate trial or
command IDs, a single robot/artifact per reviewed scope, timestamp order,
finite nonnegative distances, measured positive speeds, and explicit booleans.
CSV quoting, BOM and CRLF are supported; size/row/column bounds prevent huge
inputs. Exported JSON contains issues, counts and the maximum recorded stop
latency among complete PASS rows. No p95 or physical safety threshold is inferred.

READY_FOR_HUMAN_REVIEW means only data completeness. Every report declares
physicalVerified=false and motionAuthorized=false. Evidence file paths, actual
files, identity, timestamps, observer independence and measurement accuracy must
be verified by the responsible operator. Core/APK flags remain OFF.

Validation: all five Node suites pass, including synthetic complete data,
empty template, failures, malformed CSV, duplicates, nonfinite/negative values,
wrong time order, mixed artifacts and missing angular speed. Chrome local QA
passes blank-template review, L1–L3 scope, clear, and actual local CSV selection;
page screenshot inspected. No hardware trial or robot command was performed.

Release uses existing source backup/previous image and verifies deployed static
hashes and Core health. S5/T8 physical testing and T9 activation/physical rollback
remain pending installed APK, operator, sensor/STOP and measurement evidence.
