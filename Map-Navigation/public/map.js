/**
 * KKUL Smart Navigator - Fixed Map Display Engine (No Zoom in/out)
 * 100% Fit Responsive SVG Map Canvas with Dual-layer Dash Flow & Native Pulsing Pins
 */

// Create an SVG element with attributes (works on all browsers/WebViews,
// unlike setting innerHTML on SVG elements which fails on old Chrome/WebView).
function svgEl(tag, attrs) {
  var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if (attrs) {
    for (var k in attrs) {
      if (attrs.hasOwnProperty(k)) el.setAttribute(k, attrs[k]);
    }
  }
  return el;
}

class InteractiveMapEngine {
  constructor(options = {}) {
    this.floorImg = options.floorImg || document.getElementById('mapFloorImage');
    this.svgOverlay = options.svgOverlay || document.getElementById('mapSvgOverlay');
    
    this.svgRouteGlow = options.svgRouteGlow || document.getElementById('svgRouteGlow');
    this.svgRouteFlow = options.svgRouteFlow || document.getElementById('svgRouteFlow');
    this.svgCheckpointsLayer = options.svgCheckpointsLayer || document.getElementById('svgCheckpointsLayer');
    this.svgStairJumpsLayer = options.svgStairJumpsLayer || document.getElementById('svgStairJumpsLayer');
    this.svgPinsLayer = options.svgPinsLayer || document.getElementById('svgPinsLayer');
    this.svgCorridorsLayer = options.svgCorridorsLayer || document.getElementById('svgCorridorsLayer');

    this.currentFloor = options.initialFloor || 2; // Default to Floor 2 (Main Entrance)
    this.currentRoute = null;

    // Floor Image Map paths from the clean original map directory (/data/map/) for display
    this.floorImages = {
      1: 'data/map/page_2.png',
      2: 'data/map/page_4.png',
      3: 'data/map/page_5.png',
      4: 'data/map/page_7.png',
      5: 'data/map/page_8.png',
      6: 'data/map/page_9.png'
    };
  }

  // Switch Floor Map Image & Re-render overlay for that floor
  switchFloor(floorNumber) {
    this.currentFloor = parseInt(floorNumber);
    if (this.floorImg) {
      this.floorImg.src = this.floorImages[this.currentFloor] || `data/map/page_4.png`;
    }
    
    // Update Floor Title
    const floorTitles = {
      1: "ชั้น 1 - คลังพัสดุ, หอจดหมายเหตุ, Maker Space, ห้องดอกคูน, U-Store",
      2: "ชั้น 2 - ทางเข้าหลัก (Main Entrance), Cafe Amazon, AI Clinic, ยืม-คืน",
      3: "ชั้น 3 - Production House, ห้องกลุ่มย่อย 1302, วารสาร/วิจัย 2301, AI Corner",
      4: "ชั้น 4 - ห้องประชุมบายศรี 1401, หนังสือต่างประเทศ/ไทย 2401-2402",
      5: "ชั้น 5 - หนังสือต่างประเทศและภาษาไทย 2501-2502, มุมอ่านหนังสือ",
      6: "ชั้น 6 - หนังสือต่างประเทศและภาษาไทย 2601-2602, พื้นที่ปฏิบัติงาน"
    };

    const titleEl = document.getElementById('currentFloorTitle');
    if (titleEl) {
      titleEl.textContent = floorTitles[this.currentFloor] || `ชั้น ${this.currentFloor}`;
    }

    this.renderCurrentFloorRoute();
  }

  // Render navigation route on the current floor
  setRoute(routeData) {
    this.currentRoute = routeData;
    this.renderCurrentFloorRoute();
  }

  clearRoute() {
    this.currentRoute = null;
    if (this.svgRouteGlow) this.svgRouteGlow.setAttribute('d', '');
    if (this.svgRouteFlow) this.svgRouteFlow.setAttribute('d', '');
    if (this.svgCheckpointsLayer) this.svgCheckpointsLayer.innerHTML = '';
    if (this.svgStairJumpsLayer) this.svgStairJumpsLayer.innerHTML = '';
    if (this.svgPinsLayer) this.svgPinsLayer.innerHTML = '';
    
    const banner = document.getElementById('stairJumpBanner');
    if (banner) banner.classList.add('hidden');
  }

  renderCurrentFloorRoute() {
    if (!this.currentRoute) {
      this.clearRoute();
      return;
    }

    const start = this.currentRoute.start;
    const destination = this.currentRoute.destination;
    const nodes = this.currentRoute.nodes || [];
    const pathSteps = this.currentRoute.pathSteps || this.currentRoute.path_steps || [];
    const curFloor = this.currentFloor;

    if (!start || !destination || nodes.length === 0) {
      return;
    }

    // Construct contiguous sub-paths on this floor
    const floorSegments = [];
    let currentSegment = [];

    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      if (node.floor === curFloor) {
        currentSegment.push(node);
      } else {
        if (currentSegment.length > 0) {
          floorSegments.push(currentSegment);
          currentSegment = [];
        }
      }
    }
    if (currentSegment.length > 0) {
      floorSegments.push(currentSegment);
    }

    // Build SVG Path 'd' string
    let pathD = '';
    floorSegments.forEach(seg => {
      if (seg.length > 0) {
        pathD += `M ${seg[0].x} ${seg[0].y} `;
        for (let j = 1; j < seg.length; j++) {
          pathD += `L ${seg[j].x} ${seg[j].y} `;
        }
      }
    });

    if (this.svgRouteGlow) this.svgRouteGlow.setAttribute('d', pathD);
    if (this.svgRouteFlow) this.svgRouteFlow.setAttribute('d', pathD);

    // Clear Layers
    if (this.svgCheckpointsLayer) this.svgCheckpointsLayer.innerHTML = '';
    if (this.svgStairJumpsLayer) this.svgStairJumpsLayer.innerHTML = '';
    if (this.svgPinsLayer) this.svgPinsLayer.innerHTML = '';

    // Render Checkpoints along the current floor route
    if (this.svgCheckpointsLayer) {
      floorSegments.forEach(seg => {
        seg.forEach((n, idx) => {
          if (n.id === start.id || n.id === destination.id) return;
          
          const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
          circle.setAttribute('cx', n.x);
          circle.setAttribute('cy', n.y);
          circle.setAttribute('r', '6');
          circle.setAttribute('fill', '#ffffff');
          circle.setAttribute('stroke', '#059669');
          circle.setAttribute('stroke-width', '3');
          
          const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
          title.textContent = `${n.name_th} (${n.code || ''})`;
          circle.appendChild(title);

          this.svgCheckpointsLayer.appendChild(circle);
        });
      });
    }

    // Check for Vertical Floor Transitions (Stairs / Elevators)
    let hasFloorJump = false;
    let nextTargetFloor = null;

    pathSteps.forEach(step => {
      if ((step.type === 'stairs' || step.type === 'elevator')) {
        if (step.from.floor === curFloor) {
          hasFloorJump = true;
          nextTargetFloor = step.to.floor;
          this.renderStairJumpMarker(step.from, step.to, step.type);
        } else if (step.to.floor === curFloor) {
          this.renderStairArrivalMarker(step.to, step.from.floor, step.type);
        }
      }
    });

    // Show/Hide Floating 3D Floor Jump Notification Banner
    const banner = document.getElementById('stairJumpBanner');
    if (banner) {
      if (hasFloorJump && nextTargetFloor !== null) {
        banner.classList.remove('hidden');
        const badge = document.getElementById('stairJumpFloorBadge');
        if (badge) badge.textContent = `ชั้น ${curFloor} ➔ ชั้น ${nextTargetFloor}`;
        const jumpText = document.getElementById('stairJumpText');
        if (jumpText) jumpText.textContent = `เดินไปยัง ${nextTargetFloor > curFloor ? 'ขึ้น' : 'ลง'} บันได/ลิฟต์ เพื่อไปยังชั้น ${nextTargetFloor}`;
        
        const btnJump = document.getElementById('btnExecuteFloorJump');
        if (btnJump) {
          btnJump.onclick = () => {
            if (window.app) window.app.switchFloor(nextTargetFloor);
            else this.switchFloor(nextTargetFloor);
          };
        }
      } else {
        banner.classList.add('hidden');
      }
    }

    // Render Start Pin if on this floor
    if (start.floor === curFloor) {
      this.renderStartPin(start.x, start.y, start.name_th);
    }

    // Render Destination Pin if on this floor
    if (destination.floor === curFloor) {
      this.renderDestinationPin(destination.x, destination.y, destination.name_th);
    }
  }

  // Start Pin (🟢 Pulsing Green Pin with native SVG animation centered precisely on x, y)
  renderStartPin(x, y, name) {
    if (!this.svgPinsLayer) return;
    const g = svgEl('g', { transform: `translate(${x}, ${y})` });

    const ring = svgEl('circle', { cx: 0, cy: 0, r: 13, fill: 'none', stroke: '#10b981', 'stroke-width': 3, class: 'pin-pulse' });
    g.appendChild(ring);

    const dot = svgEl('circle', { cx: 0, cy: 0, r: 12, fill: '#059669', stroke: '#ffffff', 'stroke-width': 3 });
    g.appendChild(dot);

    const core = svgEl('circle', { cx: 0, cy: 0, r: 5, fill: '#ffffff' });
    g.appendChild(core);

    const label = svgEl('g', { transform: 'translate(0, -28)' });
    const rect = svgEl('rect', { x: -70, y: -22, width: 140, height: 22, rx: 11, fill: '#064e3b', stroke: '#34d399', 'stroke-width': 1.5 });
    label.appendChild(rect);
    const text = svgEl('text', { x: 0, y: -7, fill: '#ecfdf5', 'font-size': 11, 'font-weight': 'bold', 'text-anchor': 'middle' });
    text.textContent = 'จุดเริ่มต้น';
    label.appendChild(text);
    g.appendChild(label);

    this.svgPinsLayer.appendChild(g);
  }

  // Destination Pin (🔴 Pulsing Red Pin with native SVG animation centered precisely on x, y)
  renderDestinationPin(x, y, name) {
    if (!this.svgPinsLayer) return;
    const g = svgEl('g', { transform: `translate(${x}, ${y})` });

    const ring = svgEl('circle', { cx: 0, cy: 0, r: 13, fill: 'none', stroke: '#f43f5e', 'stroke-width': 3, class: 'pin-pulse' });
    g.appendChild(ring);

    const pinBody = svgEl('path', { d: 'M 0 0 L -11 -26 A 13 13 0 1 1 11 -26 Z', fill: '#e11d48', stroke: '#ffffff', 'stroke-width': 3 });
    g.appendChild(pinBody);

    const pinDot = svgEl('circle', { cx: 0, cy: -26, r: 5, fill: '#ffffff' });
    g.appendChild(pinDot);

    const label = svgEl('g', { transform: 'translate(0, -50)' });
    const rect = svgEl('rect', { x: -85, y: -24, width: 170, height: 24, rx: 12, fill: '#881337', stroke: '#fb7185', 'stroke-width': 1.5 });
    label.appendChild(rect);
    const text = svgEl('text', { x: 0, y: -8, fill: '#fff1f2', 'font-size': 11, 'font-weight': 'bold', 'text-anchor': 'middle' });
    text.textContent = 'จุดหมาย: ' + (name || '').slice(0, 16);
    label.appendChild(text);
    g.appendChild(label);

    this.svgPinsLayer.appendChild(g);
  }

  // 3D Stair / Elevator Transition Button on the Map
  renderStairJumpMarker(fromNode, toNode, transportType) {
    if (!this.svgStairJumpsLayer) return;
    const isUp = toNode.floor > fromNode.floor;
    const symbol = transportType === 'elevator' ? 'ELEV' : 'STAIR';
    const actionText = `${isUp ? 'ขึ้น' : 'ลง'} ชั้น ${toNode.floor}`;

    const g = svgEl('g', { class: 'stair-jump-pin', transform: `translate(${fromNode.x}, ${fromNode.y})` });

    const ring = svgEl('circle', { cx: 0, cy: 0, r: 14, fill: 'none', stroke: '#818cf8', 'stroke-width': 2.5, class: 'pin-pulse' });
    g.appendChild(ring);

    const dot = svgEl('circle', { cx: 0, cy: 0, r: 15, fill: '#4f46e5', stroke: '#ffffff', 'stroke-width': 2.5 });
    g.appendChild(dot);

    const symText = svgEl('text', { x: 0, y: 5, 'font-size': 10, 'text-anchor': 'middle', fill: '#ffffff', 'font-weight': 'bold' });
    symText.textContent = symbol;
    g.appendChild(symText);

    const label = svgEl('g', { transform: 'translate(0, -30)' });
    const rect = svgEl('rect', { x: -58, y: -24, width: 116, height: 24, rx: 12, fill: '#1e1b4b', stroke: '#a5b4fc', 'stroke-width': 1.5 });
    label.appendChild(rect);
    const text = svgEl('text', { x: 0, y: -8, fill: '#e0e7ff', 'font-size': 11, 'font-weight': 'bold', 'text-anchor': 'middle' });
    text.textContent = actionText;
    label.appendChild(text);
    g.appendChild(label);

    g.onclick = () => {
      if (window.app) window.app.switchFloor(toNode.floor);
      else this.switchFloor(toNode.floor);
    };

    this.svgStairJumpsLayer.appendChild(g);
  }

  // Arrival Marker after climbing stairs / elevator
  renderStairArrivalMarker(node, prevFloor, transportType) {
    if (!this.svgStairJumpsLayer) return;

    const g = svgEl('g', { transform: `translate(${node.x}, ${node.y})` });

    const dot = svgEl('circle', { cx: 0, cy: 0, r: 13, fill: '#0891b2', stroke: '#ffffff', 'stroke-width': 2.5 });
    g.appendChild(dot);

    const label = svgEl('g', { transform: 'translate(0, -24)' });
    const rect = svgEl('rect', { x: -58, y: -20, width: 116, height: 20, rx: 10, fill: '#164e63', stroke: '#67e8f9', 'stroke-width': 1.5 });
    label.appendChild(rect);
    const text = svgEl('text', { x: 0, y: -6, fill: '#ecfeff', 'font-size': 10, 'font-weight': 'bold', 'text-anchor': 'middle' });
    text.textContent = `มาจากชั้น ${prevFloor}`;
    label.appendChild(text);
    g.appendChild(label);

    this.svgStairJumpsLayer.appendChild(g);
  }

  // Focus the viewport on a specific point (used by clickable timeline steps).
  // Since the map is a fixed 100% viewport, this simply switches the floor and
  // highlights the target node with a temporary pulsing marker.
  focusOnPoint(x, y, _zoom = 1) {
    const layer = this.svgCheckpointsLayer;
    if (!layer) return;

    const marker = svgEl('g', { class: 'focus-pulse', transform: `translate(${x}, ${y})` });
    const ring = svgEl('circle', { cx: 0, cy: 0, r: 11, fill: 'none', stroke: '#10b981', 'stroke-width': 3, class: 'pin-pulse' });
    marker.appendChild(ring);
    const dot = svgEl('circle', { cx: 0, cy: 0, r: 8, fill: '#059669', stroke: '#ffffff', 'stroke-width': 2.5 });
    marker.appendChild(dot);

    layer.appendChild(marker);
  }

  // Remove all temporary focus/highlight markers (called when switching floor).
  clearFocusMarkers() {
    if (this.svgCheckpointsLayer) {
      this.svgCheckpointsLayer.querySelectorAll('.focus-pulse').forEach(m => m.remove());
    }
  }
}

window.InteractiveMapEngine = InteractiveMapEngine;
