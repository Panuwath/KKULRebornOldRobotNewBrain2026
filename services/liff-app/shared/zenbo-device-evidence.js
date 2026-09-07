(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboDeviceEvidence = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';
  function reportedBoolean(value) {
    return value === true ? 'รายงานว่าใช่' : value === false ? 'รายงานว่าไม่ใช่' : 'ยังไม่รายงาน';
  }
  function guards(robot, now = Date.now()) {
    const received = robot?.heartbeat_received_at_ms;
    const fresh = Number.isFinite(received) && received > 0 && now >= received && now - received <= 10000
      && !['INVALID_JSON','INVALID_SHAPE'].includes(robot?.heartbeat_payload_state);
    const guard = fresh ? robot?.safety_guard : null;
    const collision = typeof guard?.collision_guard_enabled === 'boolean' ? guard.collision_guard_enabled : null;
    const fall = typeof guard?.fall_guard_enabled === 'boolean' ? guard.fall_guard_enabled : null;
    return {collision, fall, base: fresh && guard?.base_motion_enabled === true,
      state: collision === null || fall === null ? 'UNKNOWN' : collision && fall ? 'ON' : !collision && !fall ? 'OFF' : 'PARTIAL'};
  }
  function describe(robots, selected, now = Date.now()) {
    if (selected.length !== 1) return {summary: 'เลือกหุ่นหนึ่งเครื่องเพื่อดูข้อมูล APK', rows: []};
    const robot = robots.find(item => item.robot_slug === selected[0]);
    if (!robot) return {summary: 'ยังไม่มีข้อมูลปัจจุบันของ ' + selected[0], rows: []};
    const received = robot.heartbeat_received_at_ms;
    const age = now - received;
    if (!Number.isFinite(received) || received <= 0 || age < 0 || age > 10000)
      return {summary: 'ข้อมูลของ ' + selected[0] + ' หมดอายุหรือยังไม่มี heartbeat สด กรุณารอข้อมูลใหม่', rows: []};
    if (['INVALID_JSON', 'INVALID_SHAPE'].includes(robot.heartbeat_payload_state))
      return {summary: 'รับ heartbeat จาก ' + selected[0] + ' แล้ว แต่รูปแบบ JSON ไม่ถูกต้อง ต้องตรวจหรืออัปเดตแอปบนหุ่น (' + robot.heartbeat_payload_state + ')', rows: []};
    const hash = typeof robot.apk_sha256 === 'string' && /^[a-f0-9]{64}$/i.test(robot.apk_sha256)
      ? robot.apk_sha256 : 'ยังไม่มี SHA256 ที่ถูกต้อง';
    const version = typeof robot.version_name === 'string' && robot.version_name.trim()
      ? robot.version_name.slice(0, 80) : 'ยังไม่รายงาน';
    return {
      summary: 'ข้อมูลที่ ' + selected[0] + ' รายงาน · heartbeat อายุ ' + Math.floor(age / 1000) + ' วินาที',
      rows: [
        ['เวอร์ชัน APK', version],
        ['SHA256 ของ APK', hash],
        ['Robot API พร้อม', reportedBoolean(robot.robot_api_ready)],
        ['ตัวตรวจความปลอดภัยทำงาน', reportedBoolean(robot.safety_monitor_active)],
        ['เซนเซอร์ที่จำเป็นครบ', reportedBoolean(robot.safety_monitor?.required_sensor_coverage)],
        ['เปิดป้องกันการชน', reportedBoolean(robot.safety_guard?.collision_guard_enabled)],
        ['เปิดป้องกันการตก', reportedBoolean(robot.safety_guard?.fall_guard_enabled)],
        ['รับประกันขีดจำกัดเวลาหยุด', reportedBoolean(robot.motion?.body_relative?.watchdog_hard_upper_bound)]
      ]
    };
  }
  return {describe, guards};
});
