/**
 * Zenbo Booky 3D Digital Twin Component
 * Procedural Three.js 3D Model with Telemetry & Interactive Feedback
 */

(function(window) {
  'use strict';

  function isWebGLSupported() {
    try {
      var canvas = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')));
    } catch (e) {
      return false;
    }
  }

  var ZenboTwin = function() {
    this.container = null;
    this.opts = {};
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.animId = null;
    this.isDisposed = false;
    this.isInteractive = true;

    // Groups & Meshes
    this.robotGroup = null;
    this.headGroup = null;
    this.faceMesh = null;
    this.faceCanvas = null;
    this.faceTexture = null;
    this.wheelLightsMesh = null;
    this.energyRingMesh = null;
    this.shieldMeshes = [];
    this.sonarMesh = null;
    this.driveArrowMesh = null;
    this.speechRingsMesh = null;

    // State
    this.currentRobot = null;
    this.commanded = null; // { head, face, lights }
    this.driveIntent = null;
    this.honestyPill = null;
    this.lastRenderTime = 0;

    // Pointer Interaction
    this.isPointerDown = false;
    this.prevPointerPos = { x: 0, y: 0 };
    this.targetRotationY = 0;
    this.targetHeadYaw = 0;
    this.targetHeadPitch = 0;
  };

  ZenboTwin.prototype.init = function(container, opts) {
    if (typeof container === 'string') {
      container = document.querySelector(container);
    }
    if (!container) return;

    this.container = container;
    this.opts = opts || {};
    this.isInteractive = this.opts.interactive !== false;

    if (!isWebGLSupported() || typeof window.THREE === 'undefined') {
      this.renderFallback();
      if (typeof this.opts.onFallback === 'function') {
        this.opts.onFallback('WebGL unavailable or Three.js missing');
      }
      return;
    }

    this.setupScene();
    this.setupProceduralModel();
    this.setupHonestyPill();
    this.setupInteraction();
    this.startLoop();
  };

  ZenboTwin.prototype.setupScene = function() {
    var width = this.container.clientWidth || 300;
    var height = this.container.clientHeight || 200;

    this.scene = new window.THREE.Scene();
    this.scene.background = null; // Transparent

    this.camera = new window.THREE.PerspectiveCamera(40, width / height, 0.1, 100);
    this.camera.position.set(0, 1.2, 3.8);
    this.camera.lookAt(0, 0.45, 0);

    // Lights
    var ambient = new window.THREE.AmbientLight(0xffffff, 0.7);
    this.scene.add(ambient);

    var dirLight = new window.THREE.DirectionalLight(0x38bdf8, 0.8);
    dirLight.position.set(2, 4, 3);
    this.scene.add(dirLight);

    var rimLight = new window.THREE.DirectionalLight(0x06b6d4, 0.5);
    rimLight.position.set(-2, 1, -2);
    this.scene.add(rimLight);

    this.renderer = new window.THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.container.style.position = 'relative';
    this.renderer.domElement.style.touchAction = 'none';
    this.renderer.domElement.style.cursor = this.isInteractive ? 'grab' : 'default';
    this.container.appendChild(this.renderer.domElement);

    var self = this;
    window.addEventListener('resize', function() {
      if (self.isDisposed || !self.container) return;
      var w = self.container.clientWidth;
      var h = self.container.clientHeight;
      if (w > 0 && h > 0 && self.camera && self.renderer) {
        self.camera.aspect = w / h;
        self.camera.updateProjectionMatrix();
        self.renderer.setSize(w, h);
      }
    });
  };

  ZenboTwin.prototype.setupProceduralModel = function() {
    this.robotGroup = new window.THREE.Group();
    this.scene.add(this.robotGroup);

    var whiteMat = new window.THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.3, metalness: 0.1 });
    var darkMat = new window.THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 });

    // 1. Base / Torso
    var baseGeo = new window.THREE.CylinderGeometry(0.55, 0.65, 0.7, 32);
    var baseMesh = new window.THREE.Mesh(baseGeo, whiteMat);
    baseMesh.position.y = 0.35;
    this.robotGroup.add(baseMesh);

    // 2. Wheel Lights (Torus Ring on base)
    var wheelLightGeo = new window.THREE.TorusGeometry(0.58, 0.04, 16, 32);
    var wheelLightMat = new window.THREE.MeshStandardMaterial({
      color: 0x00d031,
      emissive: 0x00d031,
      emissiveIntensity: 0.8,
      roughness: 0.2
    });
    this.wheelLightsMesh = new window.THREE.Mesh(wheelLightGeo, wheelLightMat);
    this.wheelLightsMesh.rotation.x = Math.PI / 2;
    this.wheelLightsMesh.position.y = 0.18;
    this.robotGroup.add(this.wheelLightsMesh);

    // 3. Energy / Battery Ring (Torus around middle base)
    var energyGeo = new window.THREE.TorusGeometry(0.57, 0.025, 16, 32);
    var energyMat = new window.THREE.MeshStandardMaterial({
      color: 0x10b981,
      emissive: 0x10b981,
      emissiveIntensity: 0.7
    });
    this.energyRingMesh = new window.THREE.Mesh(energyGeo, energyMat);
    this.energyRingMesh.rotation.x = Math.PI / 2;
    this.energyRingMesh.position.y = 0.52;
    this.robotGroup.add(this.energyRingMesh);

    // 4. Head Group (Neck pivot at y = 0.75)
    this.headGroup = new window.THREE.Group();
    this.headGroup.position.set(0, 0.85, 0);
    this.robotGroup.add(this.headGroup);

    // Head Sphere/Capsule
    var headGeo = new window.THREE.SphereGeometry(0.48, 32, 24);
    var headMesh = new window.THREE.Mesh(headGeo, whiteMat);
    headMesh.scale.set(1, 0.9, 0.95);
    this.headGroup.add(headMesh);

    // Face Visor with Canvas Texture
    this.faceCanvas = document.createElement('canvas');
    this.faceCanvas.width = 256;
    this.faceCanvas.height = 128;
    if (window.ZenboFaceTexture) {
      window.ZenboFaceTexture.draw(this.faceCanvas, 'DEFAULT_STILL');
    }

    this.faceTexture = new window.THREE.CanvasTexture(this.faceCanvas);
    var visorGeo = new window.THREE.CylinderGeometry(0.485, 0.485, 0.42, 32, 1, true, -Math.PI / 3, Math.PI * 2 / 3);
    var visorMat = new window.THREE.MeshBasicMaterial({
      map: this.faceTexture,
      transparent: true
    });
    this.faceMesh = new window.THREE.Mesh(visorGeo, visorMat);
    this.faceMesh.position.set(0, 0.04, 0);
    this.faceMesh.rotation.y = Math.PI;
    this.headGroup.add(this.faceMesh);

    // 5. Safety Shields (3 concentric wireframe/semi-transparent rings)
    for (var s = 0; s < 3; s++) {
      var radius = 0.85 + s * 0.18;
      var shieldGeo = new window.THREE.RingGeometry(radius, radius + 0.04, 32);
      var shieldMat = new window.THREE.MeshBasicMaterial({
        color: 0x06b6d4,
        transparent: true,
        opacity: 0.35,
        side: window.THREE.DoubleSide
      });
      var shieldMesh = new window.THREE.Mesh(shieldGeo, shieldMat);
      shieldMesh.rotation.x = Math.PI / 2;
      shieldMesh.position.y = 0.05 + s * 0.02;
      this.robotGroup.add(shieldMesh);
      this.shieldMeshes.push(shieldMesh);
    }

    // 6. Sonar Sweep Wedge
    var sonarGeo = new window.THREE.CircleGeometry(1.4, 24, 0, Math.PI / 3);
    var sonarMat = new window.THREE.MeshBasicMaterial({
      color: 0x06b6d4,
      transparent: true,
      opacity: 0.2,
      side: window.THREE.DoubleSide
    });
    this.sonarMesh = new window.THREE.Mesh(sonarGeo, sonarMat);
    this.sonarMesh.rotation.x = -Math.PI / 2;
    this.sonarMesh.rotation.z = Math.PI / 3;
    this.sonarMesh.position.y = 0.02;
    this.robotGroup.add(this.sonarMesh);
  };

  ZenboTwin.prototype.setupHonestyPill = function() {
    var pill = document.createElement('div');
    pill.className = 'zenbo-honesty-badge';
    pill.style.position = 'absolute';
    pill.style.bottom = '10px';
    pill.style.left = '50%';
    pill.style.transform = 'translateX(-50%)';
    pill.style.display = 'none';
    pill.style.pointerEvents = 'none';
    pill.innerHTML = '<i class="fa-solid fa-circle-info"></i><span>คำสั่งล่าสุด — ยังไม่ยืนยันท่าจริง</span>';
    this.container.appendChild(pill);
    this.honestyPill = pill;
  };

  ZenboTwin.prototype.setupInteraction = function() {
    var self = this;
    var dom = this.renderer.domElement;

    dom.addEventListener('pointerdown', function(e) {
      if (!self.isInteractive) return;
      self.isPointerDown = true;
      self.prevPointerPos = { x: e.clientX, y: e.clientY };
      dom.style.cursor = 'grabbing';
    });

    window.addEventListener('pointermove', function(e) {
      if (!self.isPointerDown || !self.isInteractive) return;
      var dx = e.clientX - self.prevPointerPos.x;
      var dy = e.clientY - self.prevPointerPos.y;
      self.prevPointerPos = { x: e.clientX, y: e.clientY };

      self.targetRotationY += dx * 0.01;
      self.targetHeadPitch = Math.max(-0.25, Math.min(0.8, self.targetHeadPitch - dy * 0.008));
    });

    window.addEventListener('pointerup', function() {
      self.isPointerDown = false;
      if (dom) dom.style.cursor = self.isInteractive ? 'grab' : 'default';
    });

    dom.addEventListener('click', function(e) {
      if (!self.isInteractive) return;
      var rect = dom.getBoundingClientRect();
      var yRatio = (e.clientY - rect.top) / rect.height;
      if (yRatio < 0.45 && typeof self.opts.onFaceTap === 'function') {
        self.opts.onFaceTap();
      } else if (yRatio >= 0.45 && typeof self.opts.onBaseTap === 'function') {
        self.opts.onBaseTap();
      }
    });
  };

  ZenboTwin.prototype.update = function(robot) {
    this.currentRobot = robot;
    if (!robot || this.isDisposed) return;

    // Battery / Energy Ring
    var batt = robot.battery ? (robot.battery.level || 0) : 100;
    if (this.energyRingMesh) {
      var battColor = batt > 50 ? 0x10b981 : (batt > 20 ? 0xf59e0b : 0xf43f5e);
      this.energyRingMesh.material.color.setHex(battColor);
      this.energyRingMesh.material.emissive.setHex(battColor);
    }

    // Safety Guards / Shields
    var sg = robot.safety_guard || {};
    if (this.shieldMeshes.length >= 3) {
      this.shieldMeshes[0].visible = (sg.collision_guard_enabled !== false);
      this.shieldMeshes[1].visible = (sg.fall_guard_enabled !== false);
      this.shieldMeshes[2].visible = (sg.base_motion_enabled !== false);
    }

    // Sonar safety state
    if (this.sonarMesh && robot.safety) {
      var isStop = (robot.safety.state === 'SENSOR_STOP' || (robot.safety.data && robot.safety.data.state === 'SENSOR_STOP'));
      this.sonarMesh.material.color.setHex(isStop ? 0xf43f5e : 0x06b6d4);
      this.sonarMesh.material.opacity = isStop ? 0.6 : 0.2;
    }
  };

  ZenboTwin.prototype.setCommanded = function(c) {
    this.commanded = c || null;
    if (this.honestyPill) {
      this.honestyPill.style.display = this.commanded ? 'inline-flex' : 'none';
    }

    if (c) {
      if (c.face && window.ZenboFaceTexture && this.faceCanvas) {
        window.ZenboFaceTexture.draw(this.faceCanvas, c.face);
        if (this.faceTexture) this.faceTexture.needsUpdate = true;
      }
      if (c.head) {
        if (typeof c.head.yaw === 'number') {
          this.targetHeadYaw = (c.head.yaw * Math.PI) / 180;
        }
        if (typeof c.head.pitch === 'number') {
          this.targetHeadPitch = (c.head.pitch * Math.PI) / 180;
        }
      }
      if (c.lights && this.wheelLightsMesh) {
        var colorVal = c.lights.color;
        if (typeof colorVal === 'string' && colorVal.indexOf('#') === 0) {
          colorVal = parseInt(colorVal.replace('#', '0x'), 16);
        } else if (typeof colorVal === 'string' && colorVal.indexOf('0x') === 0) {
          colorVal = parseInt(colorVal, 16);
        }
        if (typeof colorVal === 'number') {
          this.wheelLightsMesh.material.color.setHex(colorVal);
          this.wheelLightsMesh.material.emissive.setHex(colorVal);
        }
      }
    }
  };

  ZenboTwin.prototype.setDriveIntent = function(dir) {
    this.driveIntent = dir;
  };

  ZenboTwin.prototype.startLoop = function() {
    var self = this;
    function render(time) {
      if (self.isDisposed) return;
      self.animId = requestAnimationFrame(render);

      if (document.visibilityState === 'hidden') return;

      var dt = (time - self.lastRenderTime) * 0.001;
      self.lastRenderTime = time;

      // Smooth Model Rotation
      if (self.robotGroup) {
        self.robotGroup.rotation.y += (self.targetRotationY - self.robotGroup.rotation.y) * 0.1;
      }
      if (self.headGroup) {
        self.headGroup.rotation.y += (self.targetHeadYaw - self.headGroup.rotation.y) * 0.15;
        self.headGroup.rotation.x += (self.targetHeadPitch - self.headGroup.rotation.x) * 0.15;
      }

      // Wheel Light Breathing Animation
      if (self.wheelLightsMesh && self.commanded && self.commanded.lights && self.commanded.lights.mode === 'breathing') {
        var intensity = 0.4 + 0.6 * (Math.sin(time * 0.004) * 0.5 + 0.5);
        self.wheelLightsMesh.material.emissiveIntensity = intensity;
      }

      if (self.renderer && self.scene && self.camera) {
        self.renderer.render(self.scene, self.camera);
      }
    }
    this.animId = requestAnimationFrame(render);
  };

  ZenboTwin.prototype.renderFallback = function() {
    if (!this.container) return;
    this.container.innerHTML = '<div class="w-full h-full flex flex-col items-center justify-center p-4 bg-slate-900/80 rounded-xl text-center border border-slate-700/60">' +
      '<svg class="w-16 h-16 text-cyan-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
      '<circle cx="12" cy="7" r="4" stroke-width="2"/>' +
      '<path stroke-width="2" d="M6 21v-2a6 6 0 0112 0v2"/>' +
      '<circle cx="9" cy="7" r="1" fill="currentColor"/>' +
      '<circle cx="15" cy="7" r="1" fill="currentColor"/>' +
      '</svg>' +
      '<span class="text-xs font-semibold text-slate-300">หุ่นยนต์ Booky (2D Mode)</span>' +
      '<span class="text-[10px] text-slate-400 mt-1">ระบบจำลองการทำงานปกติ</span>' +
      '</div>';
  };

  ZenboTwin.prototype.destroy = function() {
    this.isDisposed = true;
    if (this.animId) cancelAnimationFrame(this.animId);
    if (this.renderer && this.renderer.domElement && this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
  };

  window.ZenboTwin3D = {
    isSupported: isWebGLSupported,
    init: function(container, opts) {
      var instance = new ZenboTwin();
      instance.init(container, opts);
      return instance;
    }
  };
})(typeof window !== 'undefined' ? window : this);
