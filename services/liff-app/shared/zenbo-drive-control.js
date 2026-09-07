(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboDriveControl = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';

  var LEVELS = [1, 2, 3, 4, 5, 6, 7];
  var LABELS = ['ช้ามาก', 'ช้า', 'นุ่มนวล', 'ปานกลาง', 'เร็ว', 'เร็วมาก', 'เร็วสุด'];

  function capabilityFromRobot(robot) {
    var body = robot && robot.motion && robot.motion.body_relative;
    if (!body || typeof body !== 'object') return null;
    return {
      supported: body.supported === true,
      robot_api_ready: robot.robot_api_ready === true,
      reported_at_ms: robot.heartbeat_received_at_ms,
      policy_max_speed_level: body.policy_max_speed_level
    };
  }

  function deriveState(options) {
    options = options || {};
    var mode = options.mode || 'relative';
    var capability = options.capability;
    var nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
    var staleAfterMs = Number.isFinite(options.staleAfterMs) ? options.staleAfterMs : 10000;
    if (mode === 'remote') return { enabled: false, reason: 'SDK_DIRECTION_ONLY', cap: 0 };
    if (options.featureEnabled === false) return { enabled: false, reason: 'RELATIVE_MOTION_DISABLED', cap: 0 };
    if (options.policyFresh === false) return { enabled: false, reason: 'STALE_CORE_POLICY', cap: 0 };
    if (!options.robotSelected) return { enabled: false, reason: 'NO_ROBOT', cap: 0 };
    if (!capability) return { enabled: false, reason: 'CAPABILITY_MISSING', cap: 0 };
    if (capability.supported !== true) return { enabled: false, reason: 'UNSUPPORTED', cap: 0 };
    if (capability.robot_api_ready !== true) return { enabled: false, reason: 'ROBOT_API_NOT_READY', cap: 0 };
    if (!Number.isFinite(capability.reported_at_ms) || capability.reported_at_ms <= 0
        || capability.reported_at_ms > nowMs
        || nowMs - capability.reported_at_ms > staleAfterMs) {
      return { enabled: false, reason: 'STALE_HEARTBEAT', cap: 0 };
    }
    var cap = Number(capability.policy_max_speed_level);
    if (!Number.isInteger(cap) || cap < 1 || cap > 7) {
      return { enabled: false, reason: 'POLICY_MISSING', cap: 0 };
    }
    return { enabled: true, reason: null, cap: cap };
  }

  function reasonText(reason) {
    return {
      RELATIVE_MOTION_DISABLED: 'ยังไม่เปิดการเคลื่อนที่ L1–L7 ต้องผ่านการทดสอบกับหุ่นจริงก่อน',
      STALE_CORE_POLICY: 'ข้อมูล policy หมดอายุ รอการเชื่อมต่อ Core ใหม่',
      SINGLE_ROBOT_REQUIRED: 'เลือกหุ่นเพียงหนึ่งเครื่องสำหรับการเคลื่อนที่แบบพิกัด',
      OPERATION_PERMIT_REQUIRED: 'กรอกรหัสอนุญาตปฏิบัติงาน',
      FIELD_PERMIT_REQUIRED: 'กรอกรหัสอนุญาตทดสอบภาคสนาม',
      SPEED_EXCEEDS_POLICY: 'ระดับความเร็วเกิน policy ที่อนุญาต',
      DISTANCE_EXCEEDS_POLICY: 'ระยะทางเกิน policy ที่อนุญาต',
      INVALID_MOTION: 'กรอกระยะหรือมุมที่ถูกต้องและไม่เป็นศูนย์ทั้งหมด',
      SDK_DIRECTION_ONLY: 'รีโมตนี้รับเฉพาะทิศทาง SDK ไม่เปิดให้เลือกระดับความเร็ว',
      NO_ROBOT: 'เลือก Zenbo ก่อนเลือกระดับความเร็ว',
      CAPABILITY_MISSING: 'ยังไม่มีข้อมูลความสามารถจาก APK',
      UNSUPPORTED: 'APK เครื่องนี้ไม่รองรับ relative speed',
      ROBOT_API_NOT_READY: 'Robot API ยังไม่พร้อม',
      STALE_HEARTBEAT: 'ข้อมูลความสามารถหมดอายุ กรุณารอ heartbeat ใหม่',
      POLICY_MISSING: 'ยังไม่มีเพดานความเร็วจาก server policy',
      MOVING: 'ล็อกระดับไว้ระหว่างหุ่นกำลังเคลื่อนที่'
    }[reason] || 'ยังไม่สามารถเลือกระดับความเร็วได้';
  }

  function createModel(options) {
    options = options || {};
    var state = deriveState(options);
    var requested = Number.isInteger(options.requestedLevel) ? options.requestedLevel : 1;
    if (requested < 1 || requested > 7) requested = 1;
    return {
      requestedLevel: requested,
      appliedLevel: Number.isInteger(options.appliedLevel) ? options.appliedLevel : null,
      moving: !!options.moving,
      state: state,
      levels: LEVELS.map(function(level, index) {
        var overCap = state.enabled && level > state.cap;
        return {
          level: level,
          label: LABELS[index],
          selected: level === requested,
          disabled: !state.enabled || !!options.moving || overCap,
          reason: overCap ? 'เกิน policy cap L' + state.cap
            : (!state.enabled ? reasonText(state.reason) : (options.moving ? reasonText('MOVING') : null)),
          warning: level >= 6
        };
      })
    };
  }

  function selectLevel(model, level, onSelect) {
    var item = model.levels.find(function(candidate) { return candidate.level === level; });
    if (!item || item.disabled) return false;
    model.requestedLevel = level;
    model.levels.forEach(function(candidate) { candidate.selected = candidate.level === level; });
    if (typeof onSelect === 'function') onSelect(level);
    return true;
  }

  function createMotionRequest(options) {
    options = options || {};
    var level = Number(options.requestedLevel);
    if (!Number.isInteger(level) || level < 1 || level > 7) {
      throw new Error('requested speed level must be an integer from 1 to 7');
    }
    ['commandId', 'sourceSessionId'].forEach(function(field) {
      if (typeof options[field] !== 'string' || !options[field]) throw new Error(field + ' is required');
    });
    var request = {
      command_id: options.commandId,
      source_session_id: options.sourceSessionId,
      source_seq: options.sourceSeq,
      issued_at_ms: options.issuedAtMs,
      expires_at_ms: options.expiresAtMs,
      motion_request: {
        control_mode: 'RELATIVE_BODY',
        x_m: options.xMeters,
        y_m: options.yMeters,
        theta_deg: options.thetaDegrees,
        requested_speed_level: level
      }
    };
    ['source_seq', 'issued_at_ms', 'expires_at_ms'].forEach(function(field) {
      if (!Number.isInteger(request[field]) || request[field] < 0) throw new Error(field + ' is invalid');
    });
    ['x_m', 'y_m', 'theta_deg'].forEach(function(field) {
      if (!Number.isFinite(request.motion_request[field])) throw new Error(field + ' is invalid');
    });
    if (request.expires_at_ms <= request.issued_at_ms) throw new Error('command expiry must follow issue time');
    return request;
  }

  function prepareRelativeSubmission(options) {
    var policy = options.corePolicy;
    var now = options.nowMs;
    function reject(code) { throw new Error(code); }
    if (!policy || policy.enabled !== true) reject('RELATIVE_MOTION_DISABLED');
    if (!Number.isFinite(now) || !Number.isFinite(policy.reported_at_ms)
        || policy.reported_at_ms > now || now - policy.reported_at_ms > 10000) reject('STALE_CORE_POLICY');
    if (!Array.isArray(options.robotSlugs) || options.robotSlugs.length !== 1
        || typeof options.robotSlugs[0] !== 'string' || !options.robotSlugs[0]) reject('SINGLE_ROBOT_REQUIRED');
    if (typeof options.operationPermitId !== 'string' || !options.operationPermitId.trim()) reject('OPERATION_PERMIT_REQUIRED');
    if (typeof options.fieldPermitId !== 'string' || !options.fieldPermitId.trim()) reject('FIELD_PERMIT_REQUIRED');
    var state = deriveState({robotSelected: true, capability: options.capability, nowMs: now});
    if (!state.enabled) reject(state.reason);
    if (!Number.isInteger(policy.max_body_speed_level) || policy.max_body_speed_level < 1
        || policy.max_body_speed_level > 7 || !Number.isFinite(policy.max_distance_m)
        || policy.max_distance_m <= 0 || !Number.isInteger(policy.hard_stop_after_ms)
        || policy.hard_stop_after_ms < 1 || policy.hard_stop_after_ms > 3000) reject('POLICY_MISSING');
    if (options.requestedLevel > Math.min(state.cap, policy.max_body_speed_level)) reject('SPEED_EXCEEDS_POLICY');
    if (![options.xMeters, options.yMeters, options.thetaDegrees].every(Number.isFinite)
        || Math.abs(options.thetaDegrees) > 360
        || (options.xMeters === 0 && options.yMeters === 0 && options.thetaDegrees === 0)) reject('INVALID_MOTION');
    if (Math.hypot(options.xMeters, options.yMeters) > policy.max_distance_m) reject('DISTANCE_EXCEEDS_POLICY');
    return {
      path: '/api/v1/robots/' + encodeURIComponent(options.robotSlugs[0]) + '/relative-motion',
      headers: {'Content-Type': 'application/json',
        'X-Operation-Permit-Id': options.operationPermitId.trim(),
        'X-Field-Permit-Id': options.fieldPermitId.trim()},
      body: createMotionRequest(Object.assign({}, options, {
        issuedAtMs: now, expiresAtMs: now + policy.hard_stop_after_ms
      }))
    };
  }

  function mount(element, options) {
    if (!element) throw new Error('speed selector mount element is required');
    options = options || {};
    var model = createModel(options);
    element.innerHTML = '';
    var group = document.createElement('fieldset');
    group.className = 'grid grid-cols-7 gap-1';
    group.setAttribute('aria-label', options.label || 'เลือกระดับความเร็ว L1 ถึง L7');
    model.levels.forEach(function(item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'L' + item.level;
      button.title = item.reason || (item.warning ? 'ระดับสูง ต้องยืนยันก่อนส่งคำสั่ง' : item.label);
      button.disabled = item.disabled;
      button.setAttribute('aria-pressed', item.selected ? 'true' : 'false');
      button.setAttribute('aria-label', 'L' + item.level + ' ' + item.label + (item.reason ? ' ' + item.reason : ''));
      button.className = 'min-h-11 rounded-lg border px-1 text-xs font-bold focus:outline-none focus:ring-2 focus:ring-cyan-300 '
        + (item.selected ? 'border-cyan-300 bg-cyan-500/20 text-cyan-200 ' : 'border-slate-600 bg-slate-900 text-slate-300 ')
        + (item.disabled ? 'cursor-not-allowed opacity-45 ' : 'hover:border-cyan-400 hover:bg-cyan-500/10 ')
        + (item.warning ? 'ring-1 ring-amber-400/40' : '');
      button.addEventListener('click', function() {
        if (!selectLevel(model, item.level, options.onSelect)) return;
        mount(element, Object.assign({}, options, { requestedLevel: item.level }));
      });
      group.appendChild(button);
    });
    var status = document.createElement('p');
    status.className = 'mt-2 text-[11px] leading-relaxed text-slate-400';
    status.setAttribute('aria-live', 'polite');
    status.textContent = model.state.enabled
      ? 'เลือก L' + model.requestedLevel + ' · Policy cap L' + model.state.cap
        + (model.appliedLevel ? ' · APK รับ L' + model.appliedLevel : ' · ยังไม่ได้ส่งคำสั่ง')
      : reasonText(model.state.reason);
    element.appendChild(group);
    element.appendChild(status);
    return model;
  }

  return {
    LEVELS: LEVELS.slice(),
    capabilityFromRobot: capabilityFromRobot,
    createModel: createModel,
    createMotionRequest: createMotionRequest,
    prepareRelativeSubmission: prepareRelativeSubmission,
    deriveState: deriveState,
    mount: mount,
    reasonText: reasonText,
    selectLevel: selectLevel
  };
});
