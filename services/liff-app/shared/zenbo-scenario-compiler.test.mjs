import assert from 'node:assert';
import compilerModule from './zenbo-scenario-compiler.js';

const compiler = compilerModule;

console.log('Testing Zenbo Scenario Compiler...');

// 1. Valid L0 Speak
const l0Doc = {
  meta: {
    scenario_id: 'user-welcome-brief',
    title: 'ต้อนรับสั้นๆ',
    description: 'ทดสอบพูดประโยคเดียว L0',
    version: '1.0.0'
  },
  blocks: [
    { id: 'b1', type: 'speak', params: { text: 'สวัสดีครับ', face: 'HAPPY', voice: 'male_child' } }
  ]
};
const resL0 = compiler.compile(l0Doc);
assert.strictEqual(resL0.ok, true, 'L0 should compile successfully');
assert.strictEqual(resL0.risk_level, 'L0', 'L0 risk level expected');
assert.strictEqual(resL0.request.scenario_id, 'user-welcome-brief');
assert.strictEqual(resL0.request.command.speak, 'สวัสดีครับ');

// 2. Valid L1 Multi-step Speak
const l1Doc = {
  meta: {
    scenario_id: 'user-story-time',
    title: 'เล่านิทาน',
    version: '1.0.0'
  },
  blocks: [
    { id: 'b1', type: 'speak', params: { text: 'กาลครั้งหนึ่งนานมาแล้ว', face: 'DEFAULT_STILL' } },
    { id: 'b2', type: 'speak', params: { text: 'มีหุ่นยนต์ใจดีตัวหนึ่ง', face: 'HAPPY' } }
  ]
};
const resL1 = compiler.compile(l1Doc);
assert.strictEqual(resL1.ok, true, 'L1 should compile');
assert.strictEqual(resL1.risk_level, 'L1');
assert.strictEqual(resL1.request.command.steps.length, 2);

// 3. Valid L2 Vision Gate (Detect Person/Face)
const l2Doc = {
  meta: {
    scenario_id: 'user-face-greet',
    title: 'ทักทายเมื่อเห็นหน้า'
  },
  blocks: [
    { id: 'b1', type: 'speak', params: { text: 'กำลังมองหาเพื่อนใหม่ครับ' } },
    {
      id: 'b2',
      type: 'vision_gate',
      params: {
        action: 'detect_face',
        interval_ms: 1000,
        timeout_ms: 8000,
        on_detect_text: 'สวัสดีครับ ยินดีที่ได้รู้จัก',
        on_timeout_text: 'ไม่เจอใครเลยครับ'
      }
    }
  ]
};
const resL2 = compiler.compile(l2Doc);
assert.strictEqual(resL2.ok, true);
assert.strictEqual(resL2.risk_level, 'L2');
assert.ok(resL2.required_capabilities.includes('VISION'));

// 4. Valid L3 Vision Gate (Gesture Point)
const l3Doc = {
  meta: { scenario_id: 'user-gesture-demo', title: 'ตรวจจับการชี้' },
  blocks: [
    { id: 'b1', type: 'vision_gate', params: { action: 'gesture_point', interval_ms: 500, timeout_ms: 5000 } }
  ]
};
const resL3 = compiler.compile(l3Doc);
assert.strictEqual(resL3.ok, true);
assert.strictEqual(resL3.risk_level, 'L3');

// 5. Valid L5 Open Display
const l5Doc = {
  meta: { scenario_id: 'user-library-map', title: 'แสดงแผนที่ห้องสมุด' },
  blocks: [
    { id: 'b1', type: 'speak', params: { text: 'นี่คือหน้าเว็บห้องสมุดครับ' } },
    { id: 'b2', type: 'open_display', params: { url: 'https://lib.kku.ac.th/floor-map' } }
  ]
};
const resL5 = compiler.compile(l5Doc);
assert.strictEqual(resL5.ok, true);
assert.strictEqual(resL5.risk_level, 'L5');
assert.ok(resL5.required_capabilities.includes('DISPLAY'));

// 6. Error Cases
// 6a. Invalid scenario_id (not starting with user-)
const badIdDoc = {
  meta: { scenario_id: 'builtin-test', title: 'ห้ามใช้ชื่อ builtin' },
  blocks: [{ id: 'b1', type: 'speak', params: { text: 'test' } }]
};
const resBadId = compiler.compile(badIdDoc);
assert.strictEqual(resBadId.ok, false);
assert.ok(resBadId.errors.some(e => e.field === 'scenario_id'));

// 6b. Untrusted Display URL
const badUrlDoc = {
  meta: { scenario_id: 'user-bad-url', title: 'URL นอก Whitelist' },
  blocks: [
    { id: 'b1', type: 'open_display', params: { url: 'https://malicious-site.com' } }
  ]
};
const resBadUrl = compiler.compile(badUrlDoc);
assert.strictEqual(resBadUrl.ok, false);
assert.ok(resBadUrl.errors.some(e => e.field === 'url'));

// 6c. Text exceeds limit
const longTextDoc = {
  meta: { scenario_id: 'user-long-text', title: 'ข้อความยาวเกินไป' },
  blocks: [
    { id: 'b1', type: 'speak', params: { text: 'A'.repeat(1005) } }
  ]
};
const resLongText = compiler.compile(longTextDoc);
assert.strictEqual(resLongText.ok, false);
assert.ok(resLongText.errors.some(e => e.field === 'text'));

console.log('All Zenbo Scenario Compiler tests passed successfully!');
