(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboFieldReadiness = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';
  var LABELS = {
    ROBOT_OFFLINE: 'ไม่พบหุ่นออนไลน์',
    STALE_HEARTBEAT: 'Heartbeat หมดอายุ',
    ROBOT_API_NOT_READY: 'Robot API ยังไม่พร้อม',
    APK_HASH_MISMATCH: 'APK ที่ติดตั้งไม่ตรงกับรุ่นที่อนุมัติ',
    APPROVED_APK_HASH_UNCONFIGURED: 'ยังไม่กำหนด hash ของ APK ที่อนุมัติ',
    COLLISION_GUARD_DISABLED: 'ระบบป้องกันการชนยังไม่เปิด',
    FALL_GUARD_DISABLED: 'ระบบป้องกันการตกยังไม่เปิด',
    BASE_MOTION_MUST_BE_LOCKED: 'ต้องล็อกการเคลื่อนที่พื้นฐานก่อนตรวจ',
    SAFETY_MONITOR_DISABLED: 'ยังไม่เปิดตัวตรวจความปลอดภัย',
    SAFETY_MONITOR_INACTIVE: 'ตัวตรวจความปลอดภัยยังไม่ทำงาน',
    REQUIRED_SENSOR_COVERAGE_MISSING: 'ข้อมูลเซนเซอร์ที่จำเป็นยังไม่ครบ',
    BODY_RELATIVE_UNSUPPORTED: 'APK ยังไม่รองรับการเคลื่อนที่แบบพิกัด',
    BODY_LIMIT_MAX_DISTANCE_M_MISSING: 'ไม่มีขีดจำกัดระยะทางจาก APK',
    BODY_LIMIT_MAX_BODY_SPEED_MISSING: 'ไม่มีขีดจำกัดความเร็วจาก APK',
    BODY_LIMIT_AUTO_STOP_MS_MISSING: 'ไม่มีขีดจำกัดเวลาหยุดจาก APK',
    BODY_SPEED_INVALID: 'ขีดจำกัดความเร็วไม่ถูกต้อง',
    APK_VERSION_UNKNOWN: 'ไม่ทราบเวอร์ชัน APK',
    MOTION_WATCHDOG_NOT_HARD_BOUND: 'ยังไม่มีหลักฐานขีดจำกัดเวลาหยุดที่รับประกันได้',
    APPLIED_POLICY_EPOCH_MISSING: 'ไม่มีรุ่น policy ที่หุ่นใช้',
    HEARTBEAT_SESSION_MISSING: 'ไม่มีรหัส session ของหุ่น',
    HEARTBEAT_SEQUENCE_MISSING: 'ไม่มีลำดับ heartbeat',
    HEARTBEAT_TIMESTAMP_MISSING: 'ไม่มีเวลาของ heartbeat',
    STALE_HEARTBEAT_TIMESTAMP: 'เวลาของ heartbeat หมดอายุ'
  };
  function describe(report, robot, now) {
    if (!report || report.robot_slug !== robot || typeof report.ready !== 'boolean'
        || !Array.isArray(report.blockers) || !report.blockers.every(function(code) { return typeof code === 'string' && code.length > 0; })
        || (report.ready !== (report.blockers.length === 0))
        || !Number.isFinite(report.checked_at_ms) || report.checked_at_ms <= 0) {
      return {status: 'invalid', summary: 'ข้อมูลตรวจสอบไม่สมบูรณ์ กรุณาตรวจใหม่', blockers: []};
    }
    if (report.checked_at_ms > now || now - report.checked_at_ms > 10000) {
      return {status: 'stale', summary: 'ผลตรวจหมดอายุ กรุณาตรวจใหม่', blockers: []};
    }
    return {status: report.ready ? 'ready' : 'blocked', checkedAtMs: report.checked_at_ms,
      summary: report.ready ? 'ผ่านเงื่อนไขที่ Core ตรวจได้ ยังไม่ใช่ผลสอบเทียบหรืออนุญาตให้เคลื่อนที่'
        : 'ยังไม่พร้อม: ' + report.blockers.length + ' เงื่อนไข',
      blockers: report.blockers.map(function(code) { return (LABELS[code] || 'เงื่อนไขเพิ่มเติมจาก Core') + ' (' + code + ')'; })};
  }
  function createReader(options) {
    var robot = null, generation = 0, report = null, loading = false, failure = null;
    var now = options.now || Date.now;
    function state() {
      if (!robot) return {status: 'unselected', summary: 'เลือกหุ่นหนึ่งเครื่องเพื่อตรวจความพร้อม', blockers: []};
      if (loading) return {status: 'loading', summary: 'กำลังอ่านผลตรวจจาก Core', blockers: []};
      if (failure) return {status: 'error', summary: failure, blockers: []};
      if (!report) return {status: 'unchecked', summary: 'ยังไม่ได้ตรวจความพร้อมของ ' + robot, blockers: []};
      return describe(report, robot, now());
    }
    return {
      select: function(slug) {
        if (slug === robot) return;
        robot = slug; generation++; report = null; loading = false; failure = null;
      },
      state: state,
      refresh: async function() {
        if (!robot || loading) return;
        var requestRobot = robot, requestGeneration = ++generation;
        loading = true; report = null; failure = null;
        try {
          var response = await options.fetch(options.apiBase + '/api/v1/robots/' + encodeURIComponent(requestRobot) + '/field-calibration',
            {method: 'GET', cache: 'no-store'});
          if (!response.ok) throw new Error(response.status === 404 ? 'ROBOT_OFFLINE' : 'HTTP_' + response.status);
          var result = await response.json();
          if (requestGeneration === generation) report = result;
        } catch (error) {
          if (requestGeneration === generation) failure = error.message === 'ROBOT_OFFLINE'
            ? 'ไม่พบหุ่นออนไลน์ กรุณาตรวจการเชื่อมต่อ' : 'อ่านผลตรวจไม่ได้ กรุณาตรวจการเชื่อมต่อหรือเข้าสู่ระบบใหม่';
        } finally {
          if (requestGeneration === generation) loading = false;
        }
      }
    };
  }
  return {describe: describe, createReader: createReader};
});
