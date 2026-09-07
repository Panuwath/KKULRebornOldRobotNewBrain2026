(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboCalibrationEvidence = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';
  const columns = ('level,direction,trial,command_id,apk_sha256,operator,permit_id,issued_at_ms,apk_received_at_ms,sdk_submitted_at_ms,physical_onset_at_ms,stop_requested_at_ms,physical_stop_at_ms,stop_distance_m,overshoot_m,velocity_m_s,sensor_ok,no_overlap,no_resume,result,evidence_path,robot_slug,source_sha,observer,instrument,timebase,floor_conditions,angular_velocity_deg_s,angular_stop_distance_deg,angular_overshoot_deg').split(',');
  const directions = ['forward','backward','left','right'];
  const times = ['issued_at_ms','apk_received_at_ms','sdk_submitted_at_ms','physical_onset_at_ms','stop_requested_at_ms','physical_stop_at_ms'];
  function parse(text) {
    if (typeof text !== 'string' || text.length > 1000000) throw new Error('ไฟล์ต้องมีขนาดไม่เกิน 1 MB');
    text = text.replace(/^\uFEFF/, '');
    const rows = []; let row = [], cell = '', quoted = false, closed = false;
    function endCell() { row.push(cell); cell = ''; closed = false; }
    function endRow() { endCell(); if (row.some(value => value !== '')) rows.push(row); row = []; }
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else { quoted = false; closed = true; } }
        else cell += c;
      } else if (c === ',') endCell();
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; endRow(); }
      else if (c === '"' && cell === '' && !closed) quoted = true;
      else { if (closed || c === '"') throw new Error('รูปแบบ CSV ไม่ถูกต้อง'); cell += c; }
      if (rows.length > 1000 || row.length > 100) throw new Error('จำนวนแถวหรือคอลัมน์มากเกินไป');
    }
    if (quoted) throw new Error('CSV มีเครื่องหมายคำพูดที่ยังไม่ปิด');
    if (cell || row.length || closed) endRow();
    return rows;
  }
  function template() {
    const rows = [columns.join(',')];
    for (let level=1; level<=7; level++) for (const direction of directions) for (let trial=1; trial<=3; trial++) {
      rows.push([level,direction,trial,...Array(columns.length-3).fill('')].join(','));
    }
    return rows.join('\n') + '\n';
  }
  function review(text, maxLevel = 1) {
    if (!Number.isInteger(maxLevel) || maxLevel < 1 || maxLevel > 7) throw new Error('ขอบเขตต้องเป็น L1 ถึง L7');
    const table = parse(text), header = table.shift() || [];
    if (new Set(header).size !== header.length) throw new Error('ชื่อคอลัมน์ซ้ำ');
    const missing = columns.filter(name => !header.includes(name));
    if (missing.length) throw new Error('ขาดคอลัมน์: ' + missing.join(', '));
    const issues = [], keys = new Set(), commands = new Set(), artifacts = new Set();
    let completeRows = 0, failedRows = 0, maxStopLatencyMs = null;
    function issue(row, code) { issues.push({row, code}); }
    for (const [index, values] of table.entries()) {
      const rowNumber = index + 2;
      if (values.length !== header.length) { issue(rowNumber, 'COLUMN_COUNT'); continue; }
      const row = Object.fromEntries(header.map((name, i) => [name, values[i].trim()]));
      const level=Number(row.level), trial=Number(row.trial);
      if (!/^[1-7]$/.test(row.level) || !/^[1-3]$/.test(row.trial) || !directions.includes(row.direction)) { issue(rowNumber, 'INVALID_TRIAL_KEY'); continue; }
      if (level > maxLevel) continue;
      const key = [level,row.direction,trial].join('/');
      if (keys.has(key)) { issue(rowNumber, 'DUPLICATE_TRIAL'); continue; } keys.add(key);
      const before = issues.length;
      const required = columns.filter(name => !['velocity_m_s','angular_velocity_deg_s','stop_distance_m','overshoot_m','angular_stop_distance_deg','angular_overshoot_deg'].includes(name));
      const absent = required.filter(name => !row[name]);
      if (absent.length) issue(rowNumber, 'MISSING: ' + absent.join(', '));
      if (row.result === 'FAIL') failedRows++;
      if (row.result && !['PASS','FAIL'].includes(row.result)) issue(rowNumber, 'RESULT_MUST_BE_PASS_OR_FAIL');
      if (row.apk_sha256 && !/^[a-f0-9]{64}$/i.test(row.apk_sha256)) issue(rowNumber, 'INVALID_APK_HASH');
      if (row.source_sha && !/^[a-f0-9]{40}$/i.test(row.source_sha)) issue(rowNumber, 'INVALID_SOURCE_SHA');
      if (row.command_id) { if (commands.has(row.command_id)) issue(rowNumber, 'DUPLICATE_COMMAND'); commands.add(row.command_id); }
      if (row.robot_slug && row.apk_sha256 && row.source_sha) artifacts.add([row.robot_slug,row.apk_sha256.toLowerCase(),row.source_sha.toLowerCase()].join('/'));
      const numeric = name => row[name] !== '' && Number.isFinite(Number(row[name])) && Number(row[name]) >= 0;
      const turn = ['left','right'].includes(row.direction);
      for (const name of (turn ? ['angular_stop_distance_deg','angular_overshoot_deg'] : ['stop_distance_m','overshoot_m'])) {
        if (!numeric(name)) issue(rowNumber, 'MEASUREMENT_REQUIRED: ' + name);
      }
      const speed = ['left','right'].includes(row.direction) ? 'angular_velocity_deg_s' : 'velocity_m_s';
      if (!numeric(speed) || Number(row[speed]) === 0) issue(rowNumber, 'MEASURED_SPEED_REQUIRED: ' + speed);
      const timestampsValid = times.every(name => /^\d+$/.test(row[name]) && Number.isSafeInteger(Number(row[name])) && Number(row[name]) > 0);
      if (times.some(name => row[name]) && !timestampsValid) issue(rowNumber, 'INVALID_TIMESTAMPS');
      if (timestampsValid && times.some((name,i) => i && Number(row[name]) < Number(row[times[i-1]]))) issue(rowNumber, 'TIMESTAMP_ORDER');
      for (const name of ['sensor_ok','no_overlap','no_resume']) {
        if (row[name] && !['true','false'].includes(row[name])) issue(rowNumber, 'INVALID_' + name);
        if (row[name] === 'false') issue(rowNumber, 'SAFETY_FAILURE: ' + name);
      }
      if (row.result === 'PASS' && before === issues.length) {
        completeRows++;
        maxStopLatencyMs = Math.max(maxStopLatencyMs || 0, Number(row.physical_stop_at_ms) - Number(row.stop_requested_at_ms));
      }
    }
    for (let level=1;level<=maxLevel;level++) for (const direction of directions) for (let trial=1;trial<=3;trial++) {
      const key=[level,direction,trial].join('/'); if (!keys.has(key)) issue(null,'MISSING_TRIAL: '+key);
    }
    if (artifacts.size > 1) issue(null,'MIXED_ROBOT_OR_ARTIFACT');
    return {schemaVersion:1, maxLevel, expectedRows:maxLevel*12, completeRows, failedRows, issues,
      maxRecordedStopLatencyMs:maxStopLatencyMs,
      status:failedRows ? 'RECORDED_FAILURES' : (issues.length ? 'INCOMPLETE' : 'READY_FOR_HUMAN_REVIEW'),
      physicalVerified:false, motionAuthorized:false};
  }
  return {columns:columns.slice(),parse,template,review};
});
