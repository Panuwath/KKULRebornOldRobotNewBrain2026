# Zenbo LIFF Contracts & Interfaces

เอกสารสัญญาระหว่างโมดูล (Contracts) สำหรับระบบ Zenbo LIFF: Digital Twin 3D, Scenario Builder, Shared Navigation และ Backend APIs

---

## 1. Shared Navigation & Theme

### 1.1 `services/liff-app/shared/zenbo-theme.css`
- Design Tokens: Slate-950/900 background, Cyan/Emerald accents, Amber warnings, Rose stop/alerts.
- Glassmorphism utility classes: `.zenbo-glass-panel`, `.zenbo-glass-card`, `.zenbo-glow-cyan`, `.zenbo-glow-emerald`, `.zenbo-glow-amber`, `.zenbo-glow-rose`.
- Typography: Google Fonts `Prompt` (Headings/Body) + `JetBrains Mono` / `Inter` (Telemetry/Code).

### 1.2 `window.ZenboNav` (`services/liff-app/shared/zenbo-nav.js`)
```javascript
window.ZenboNav = {
  ITEMS: [
    { id: 'home', href: '/liff/', label: 'หน้าหลัก', icon: 'fa-solid fa-house', activeColor: 'text-cyan-400' },
    { id: 'control', href: '/liff/control/', label: 'จอยสติ๊ก', icon: 'fa-solid fa-gamepad', activeColor: 'text-indigo-400' },
    { id: 'scenario', href: '/liff/scenario/', label: 'สถานการณ์', icon: 'fa-solid fa-masks-theater', activeColor: 'text-purple-400' },
    { id: 'command', href: '/liff/command/', label: 'สั่งงาน AI', icon: 'fa-solid fa-wand-magic-sparkles', activeColor: 'text-amber-400' },
    { id: 'history', href: '/liff/history/', label: 'ประวัติ', icon: 'fa-solid fa-clock-rotate-left', activeColor: 'text-emerald-400' }
  ],
  render: function(opts) { ... }
};
```

---

## 2. 3D Digital Twin & Face Textures

### 2.1 `window.ZenboFaceTexture` (`services/liff-app/shared/zenbo-face-texture.js`)
```javascript
window.ZenboFaceTexture = {
  FACES: [
    'DEFAULT_STILL', 'HAPPY', 'PLEASED', 'PROUD', 'CONFIDENT',
    'INTERESTED', 'EXPECTING', 'SERIOUS', 'SINGING'
  ],
  draw: function(canvas, faceName, opts) { ... }
};
```

### 2.2 `window.ZenboTwin3D` (`services/liff-app/shared/zenbo-twin-3d.js`)
```javascript
window.ZenboTwin3D = {
  isSupported: function() { ... }, // boolean WebGL available
  init: function(container, opts) { ... },
  update: function(robot) { ... }, // item จาก /api/v1/robots
  setCommanded: function(command) { ... }, // { head: {yaw, pitch}, face: '...', lights: {mode, color, brightness} }
  setDriveIntent: function(dir) { ... }, // 'FORWARD'|'BACKWARD'|'TURN_LEFT'|'TURN_RIGHT'|null
  playPreview: function(command, opts) { ... },
  stopPreview: function() { ... },
  setInteractive: function(enabled) { ... },
  destroy: function() { ... }
};
```

---

## 3. Scenario Compiler & Block Rules

### 3.1 `window.ZenboScenarioCompiler` (`services/liff-app/shared/zenbo-scenario-compiler.js`)
```javascript
// Supports both Browser (window.ZenboScenarioCompiler) and Node.js (module.exports)
const BLOCK_TYPES = [
  'speak', 'head', 'head_sequence', 'wheel_lights',
  'vision_gate', 'branch_detect', 'branch_timeout', 'prompt', 'open_display', 'end'
];

function compile(builderDoc, schema) {
  // Returns: { ok: boolean, request?: ScenarioDefinitionRequest, risk_level?: 'L0'..'L5', required_capabilities?: string[], errors: [...] }
}
```

---

## 4. Backend APIs (`services/core-api/scenario_builder.py`)

- `GET /api/v1/scenario-builder/schema` (Public)
- `POST /api/v1/scenario-drafts` (Requires Web Session with `operator` or `admin` role)
- `GET /api/v1/scenario-drafts` (Requires Web Session with `operator` or `admin` role)
- `DELETE /api/v1/scenario-drafts/{scenario_id}` (Requires Web Session with `admin` role)
- Telemetry: `_remember_robot()` populates `robot["last_events"][event_kind] = event`.
