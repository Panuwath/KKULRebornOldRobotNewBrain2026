/**
 * Zenbo Scenario Compiler (Client-Side)
 * Compiles visual BuilderDoc into a strict ScenarioDefinitionRequest (L0-L5)
 * Dual runtime: Browser (window.ZenboScenarioCompiler) and Node.js (CommonJS)
 */

(function(root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ZenboScenarioCompiler = factory();
  }
})(typeof self !== 'undefined' ? self : this, function() {
  'use strict';

  var BLOCK_TYPES = [
    'speak', 'head', 'head_sequence', 'wheel_lights',
    'vision_gate', 'branch_detect', 'branch_timeout', 'prompt', 'open_display', 'end'
  ];

  var DEFAULT_SCHEMA = {
    voice_profiles: [
      { id: 'female_sweet', label: 'เสียงผู้หญิงหวาน' },
      { id: 'female_young', label: 'เสียงวัยรุ่นหญิง' },
      { id: 'female_child', label: 'เสียงเด็กหญิง' },
      { id: 'male_warm', label: 'เสียงผู้ชายอบอุ่น' },
      { id: 'male_young', label: 'เสียงวัยรุ่นชาย' },
      { id: 'male_child', label: 'เสียงเด็กชาย' }
    ],
    faces: [
      'DEFAULT_STILL', 'HAPPY', 'PLEASED', 'PROUD', 'CONFIDENT',
      'INTERESTED', 'EXPECTING', 'SERIOUS', 'SINGING'
    ],
    wheel_light_modes: ['breathing', 'blinking', 'marquee', 'static', 'off', 'rainbow'],
    vision_actions: ['detect_face', 'detect_person', 'gesture_point'],
    trusted_display_urls: [
      'https://lib.kku.ac.th',
      'https://libn.kku.ac.th',
      'https://library.kku.ac.th'
    ],
    limits: {
      text_max: 1000,
      steps_min: 1,
      steps_max: 8,
      outcome_min: 1,
      outcome_max: 4,
      head: { yaw: [-45, 45], pitch: [-15, 55], speed: [1, 5], delay_ms_max: 10000 },
      gate: { interval_ms: [250, 5000], timeout_ms: [3000, 30000] },
      scenario_id_pattern: '^user-[a-z0-9][a-z0-9_-]*$'
    }
  };

  function compile(doc, schema) {
    schema = schema || DEFAULT_SCHEMA;
    var errors = [];

    if (!doc || typeof doc !== 'object') {
      return { ok: false, errors: [{ message_th: 'ข้อมูลเอกสารสถานการณ์ไม่ถูกต้อง' }] };
    }

    var meta = doc.meta || {};
    var scenarioId = (meta.scenario_id || '').trim();
    var title = (meta.title || '').trim();
    var description = (meta.description || '').trim();
    var version = (meta.version || '1.0.0').trim();

    var idRegex = new RegExp(schema.limits.scenario_id_pattern);
    if (!scenarioId || !idRegex.test(scenarioId)) {
      errors.push({
        field: 'scenario_id',
        message_th: 'รหัสสถานการณ์ต้องขึ้นต้นด้วย user- และประกอบด้วยตัวพิมพ์เล็ก ตัวเลข ขีดลบ หรือขีดล่างเท่านั้น'
      });
    }

    if (!title) {
      errors.push({ field: 'title', message_th: 'กรุณาระบุชื่อสถานการณ์' });
    }

    var rawBlocks = doc.blocks || [];
    var filteredBlocks = [];
    for (var b = 0; b < rawBlocks.length; b++) {
      if (rawBlocks[b].type !== 'end') {
        filteredBlocks.push(rawBlocks[b]);
      }
    }

    if (filteredBlocks.length < schema.limits.steps_min) {
      errors.push({ message_th: 'ต้องมีบล็อกคำสั่งอย่างน้อย 1 ขั้นตอน' });
    }
    if (filteredBlocks.length > schema.limits.steps_max) {
      errors.push({ message_th: 'มีขั้นตอนคำสั่งเกินขีดจำกัดสูงสุด (ไม่เกิน 8 ขั้นตอน)' });
    }

    var requiredCapabilities = ['SPEAK'];
    var riskLevel = 'L0';
    var steps = [];
    var visionGate = null;
    var promptStep = null;
    var secondGate = null;
    var openDisplayUrl = null;

    var gateCount = 0;

    for (var i = 0; i < filteredBlocks.length; i++) {
      var blk = filteredBlocks[i];
      var p = blk.params || {};

      if (blk.type === 'speak') {
        var text = (p.text || '').trim();
        if (!text) {
          errors.push({ blockId: blk.id, field: 'text', message_th: 'กรุณาระบุข้อความที่ต้องการให้หุ่นยนต์พูด' });
        } else if (text.length > schema.limits.text_max) {
          errors.push({ blockId: blk.id, field: 'text', message_th: 'ข้อความยาวเกินกำหนด (สูงสุด 1,000 ตัวอักษร)' });
        }

        var face = p.face || 'DEFAULT_STILL';
        if (schema.faces.indexOf(face) === -1) {
          errors.push({ blockId: blk.id, field: 'face', message_th: 'หน้าตาหุ่นยนต์ที่เลือกไม่ถูกต้อง' });
        }

        var voice = p.voice || 'female_sweet';
        var stepObj = {
          text: text,
          face: face,
          voice: voice
        };

        if (p.rate) stepObj.rate = p.rate;
        if (p.pitch) stepObj.pitch = p.pitch;

        if (p.head) {
          stepObj.head = {
            yaw: Math.max(schema.limits.head.yaw[0], Math.min(schema.limits.head.yaw[1], p.head.yaw || 0)),
            pitch: Math.max(schema.limits.head.pitch[0], Math.min(schema.limits.head.pitch[1], p.head.pitch || 0))
          };
          if (requiredCapabilities.indexOf('HEAD_MOVEMENT') === -1) requiredCapabilities.push('HEAD_MOVEMENT');
        }

        if (p.wheel_lights) {
          stepObj.wheel_lights = {
            mode: p.wheel_lights.mode || 'breathing',
            color: p.wheel_lights.color || '#00d031',
            brightness: p.wheel_lights.brightness || 10
          };
          if (requiredCapabilities.indexOf('WHEEL_LIGHTS') === -1) requiredCapabilities.push('WHEEL_LIGHTS');
        }

        steps.push(stepObj);
      } else if (blk.type === 'vision_gate') {
        gateCount++;
        var action = p.action || 'detect_face';
        if (schema.vision_actions.indexOf(action) === -1) {
          errors.push({ blockId: blk.id, field: 'action', message_th: 'การตรวจจับ Vision ไม่ถูกต้อง' });
        }
        var intervalMs = p.interval_ms || 1000;
        var timeoutMs = p.timeout_ms || 10000;

        if (intervalMs < schema.limits.gate.interval_ms[0] || intervalMs > schema.limits.gate.interval_ms[1]) {
          errors.push({ blockId: blk.id, field: 'interval_ms', message_th: 'ช่วงเวลาตรวจจับต้องอยู่ระหว่าง 250 - 5,000 มิลลิวินาที' });
        }
        if (timeoutMs < schema.limits.gate.timeout_ms[0] || timeoutMs > schema.limits.gate.timeout_ms[1]) {
          errors.push({ blockId: blk.id, field: 'timeout_ms', message_th: 'เวลารอหมดอายุต้องอยู่ระหว่าง 3,000 - 30,000 มิลลิวินาที' });
        }

        var gateObj = {
          action: action,
          interval_ms: intervalMs,
          timeout_ms: timeoutMs,
          debug_preview: false,
          on_detect: { steps: [{ text: p.on_detect_text || 'ยินดีต้อนรับครับ', face: 'HAPPY' }] },
          on_timeout: { steps: [{ text: p.on_timeout_text || 'ขออภัยครับ ไม่พบใครเลย', face: 'DEFAULT_STILL' }] }
        };

        if (gateCount === 1) {
          visionGate = gateObj;
          if (action === 'gesture_point') {
            riskLevel = 'L3';
          } else {
            riskLevel = 'L2';
          }
          if (requiredCapabilities.indexOf('VISION') === -1) requiredCapabilities.push('VISION');
        } else if (gateCount === 2) {
          secondGate = gateObj;
          riskLevel = 'L4';
        }
      } else if (blk.type === 'open_display') {
        var url = (p.url || '').trim();
        var isTrusted = false;
        for (var t = 0; t < schema.trusted_display_urls.length; t++) {
          if (url.indexOf(schema.trusted_display_urls[t]) === 0) {
            isTrusted = true;
            break;
          }
        }
        if (!isTrusted) {
          errors.push({ blockId: blk.id, field: 'url', message_th: 'URL หน้าจอต้องเป็นโดเมนที่ได้รับอนุญาตของ KKU Library เท่านั้น' });
        }
        openDisplayUrl = url;
        riskLevel = 'L5';
        if (requiredCapabilities.indexOf('DISPLAY') === -1) requiredCapabilities.push('DISPLAY');
      }
    }

    if (openDisplayUrl) {
      riskLevel = 'L5';
    } else if (gateCount === 0) {
      riskLevel = steps.length <= 1 ? 'L0' : 'L1';
    }

    if (errors.length > 0) {
      return { ok: false, errors: errors };
    }

    // Build standard command payload
    var command = {};
    if (steps.length === 1 && riskLevel === 'L0') {
      command.speak = steps[0].text;
      command.face = steps[0].face;
      command.voice = steps[0].voice;
      if (steps[0].head) command.head = steps[0].head;
      if (steps[0].wheel_lights) command.wheel_lights = steps[0].wheel_lights;
    } else {
      command.steps = steps;
    }

    if (visionGate) {
      command.vision_gate = visionGate;
    }
    if (openDisplayUrl) {
      command.display_url = openDisplayUrl;
    }

    var request = {
      scenario_id: scenarioId,
      version: version,
      title: title,
      description: description || title,
      risk_level: riskLevel,
      required_capabilities: requiredCapabilities,
      command: command
    };

    return {
      ok: true,
      risk_level: riskLevel,
      required_capabilities: requiredCapabilities,
      request: request,
      errors: []
    };
  }

  return {
    BLOCK_TYPES: BLOCK_TYPES,
    DEFAULT_SCHEMA: DEFAULT_SCHEMA,
    compile: compile
  };
});
