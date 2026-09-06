(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ZenboDriveControl = factory();
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';

  var LEVELS = [1, 2, 3, 4, 5, 6, 7];
  var LABELS = ['ช้ามาก', 'ช้า', 'นุ่มนวล', 'ปานกลาง', 'เร็ว', 'เร็วมาก', 'เร็วสุด'];

  function deriveState(options) {
    options = options || {};
    var mode = options.mode || 'relative';
    var capability = options.capability;
    var nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
    var staleAfterMs = Number.isFinite(options.staleAfterMs) ? options.staleAfterMs : 10000;
    if (mode === 'remote') return { enabled: false, reason: 'SDK_DIRECTION_ONLY', cap: 0 };
    if (!options.robotSelected) return { enabled: false, reason: 'NO_ROBOT', cap: 0 };
    if (!capability) return { enabled: false, reason: 'CAPABILITY_MISSING', cap: 0 };
    if (!capability.supported) return { enabled: false, reason: 'UNSUPPORTED', cap: 0 };
    if (!capability.robot_api_ready) return { enabled: false, reason: 'ROBOT_API_NOT_READY', cap: 0 };
    if (!Number.isFinite(capability.reported_at_ms)
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
    createModel: createModel,
    createMotionRequest: createMotionRequest,
    deriveState: deriveState,
    mount: mount,
    reasonText: reasonText,
    selectLevel: selectLevel
  };
});
