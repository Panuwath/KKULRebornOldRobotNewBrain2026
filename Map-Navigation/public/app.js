/**
 * KKUL Smart Navigator - Main Application Coordinator
 * High-Legibility Typography & Responsive Navigation
 */

class AppController {
  constructor() {
    this.map = new InteractiveMapEngine();
    this.search = new SmartSearchController();

    this.startNode = null;
    this.destNode = null;
    this.currentRoute = null;

    this.initFloorButtons();
    this.initAppButtons();
    this.initDefaultRoute();
  }

  initFloorButtons() {
    const floorBtns = document.querySelectorAll('.floor-btn');
    floorBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const floor = parseInt(btn.getAttribute('data-floor'));
        this.switchFloor(floor);
      });
    });
  }

  switchFloor(floorNumber) {
    document.querySelectorAll('.floor-btn').forEach(b => {
      const f = parseInt(b.getAttribute('data-floor'));
      if (f === floorNumber) {
        b.classList.add('active-floor');
      } else {
        b.classList.remove('active-floor');
      }
    });

    this.map.switchFloor(floorNumber);
  }

  initAppButtons() {
    // Swap Start & Destination
    const swapBtn = document.getElementById('btnSwapRoute');
    if (swapBtn) swapBtn.addEventListener('click', () => {
      if (this.startNode && this.destNode) {
        const tmp = this.startNode;
        this.startNode = this.destNode;
        this.destNode = tmp;
        this.updateNodeLabels();
        this.calculateRoute();
      }
    });

    // Find Route Button
    const findBtn = document.getElementById('btnFindRoute');
    if (findBtn) findBtn.addEventListener('click', () => {
      this.calculateRoute();
    });

    // Clear Route Button
    const clearBtn = document.getElementById('btnClearRoute');
    if (clearBtn) clearBtn.addEventListener('click', () => {
      this.clearRoute();
    });
  }

  async initDefaultRoute() {
    const urlParams = new URLSearchParams(window.location.search);
    const fromParam = urlParams.get('from') || 'poi_f2_main_entrance';
    const toParam = urlParams.get('to') || 'r3206';

    try {
      const res = await fetch(`api/route?from=${encodeURIComponent(fromParam)}&to=${encodeURIComponent(toParam)}`);
      const data = await res.json();
      if (data.success) {
        const rData = data.data || data;
        this.startNode = rData.start;
        this.destNode = rData.destination;
        this.updateNodeLabels();
        this.currentRoute = rData;
        this.map.switchFloor(rData.start.floor);
        this.map.setRoute(rData);
        this.renderTimeline(rData);
        this.updateFloorRouteGlow(rData.passedFloors || rData.passed_floors || []);
      }
    } catch (err) {
      console.error('Initial route failed:', err);
    }
  }

  setStart(node) {
    this.startNode = node;
    this.updateNodeLabels();
    this.calculateRoute();
    if (this.map.currentFloor !== node.floor) {
      this.switchFloor(node.floor);
    }
  }

  setDestination(node) {
    this.destNode = node;
    this.updateNodeLabels();
    this.calculateRoute();
    if (this.startNode && this.map.currentFloor !== this.startNode.floor) {
      this.switchFloor(this.startNode.floor);
    }
  }

  updateNodeLabels() {
    const startDisplay = document.getElementById('startNameDisplay');
    const destDisplay = document.getElementById('destNameDisplay');

    if (startDisplay && this.startNode) {
      startDisplay.textContent = `${this.startNode.name_th} (ชั้น ${this.startNode.floor})`;
    }
    if (destDisplay && this.destNode) {
      destDisplay.textContent = `${this.destNode.name_th} (ชั้น ${this.destNode.floor})`;
    }
  }

  async calculateRoute() {
    if (!this.startNode || !this.destNode) return;

    try {
      const res = await fetch(`api/route?from=${encodeURIComponent(this.startNode.id)}&to=${encodeURIComponent(this.destNode.id)}`);
      const data = await res.json();

      if (data.success) {
        const rData = data.data || data;
        this.currentRoute = rData;
        this.map.setRoute(this.currentRoute);
        this.renderTimeline(this.currentRoute);
        this.updateFloorRouteGlow(this.currentRoute.passedFloors || this.currentRoute.passed_floors || []);
      } else {
        alert(data.error || 'ไม่พบเส้นทาง');
      }
    } catch (err) {
      console.error('Error fetching route:', err);
    }
  }

  async findNearestAmenity(type = 'restroom') {
    if (!this.startNode) {
      this.startNode = { id: "poi_f2_main_entrance", name_th: "ประตูทางเข้าหลัก Main Entrance อาคาร 3 (ชั้น 2)", floor: 2 };
      this.updateNodeLabels();
    }

    try {
      const res = await fetch(`api/nearest-amenity?from=${encodeURIComponent(this.startNode.id)}&type=${type}`);
      const data = await res.json();

      if (data.success) {
        const rData = data.data || data;
        this.destNode = rData.destination;
        this.updateNodeLabels();
        this.currentRoute = rData;
        this.map.setRoute(this.currentRoute);
        this.renderTimeline(this.currentRoute);
        this.updateFloorRouteGlow(this.currentRoute.passedFloors || this.currentRoute.passed_floors || []);
      } else {
        alert(data.error || `ไม่พบ${type}ที่ใกล้ที่สุด`);
      }
    } catch (err) {
      console.error('Error fetching nearest amenity:', err);
    }
  }

  updateFloorRouteGlow(passedFloors = []) {
    const floorBtns = document.querySelectorAll('.floor-btn');
    floorBtns.forEach(btn => {
      const f = parseInt(btn.getAttribute('data-floor'));
      if (passedFloors.includes(f)) {
        btn.classList.add('in-route');
      } else {
        btn.classList.remove('in-route');
      }
    });
  }

  renderTimeline(route) {
    const instructions = route.instructions || [];
    const dist = route.totalDistanceMeters || route.total_distance_meters || 0;
    const mins = route.estimatedMinutes || route.estimated_minutes || 1;
    const stepCount = route.stepCount || route.step_count || instructions.length;
    
    document.getElementById('summaryDistance').textContent = `${dist} m`;
    document.getElementById('summaryTime').textContent = `~${mins} นาที`;
    document.getElementById('summarySteps').textContent = `${stepCount} ขั้นตอน`;

    const container = document.getElementById('timelineContainer');
    container.innerHTML = '';

    instructions.forEach((step, index) => {
      const card = document.createElement('div');
      card.className = 'group p-4 rounded-2xl bg-white hover:bg-emerald-50 border border-slate-300 hover:border-emerald-500 transition-all cursor-pointer shadow-xs relative overflow-hidden';

      let badgeColor = 'bg-slate-100 text-slate-800 border-slate-300';
      let iconHtml = '<i data-lucide="navigation" class="w-4 h-4 text-emerald-700"></i>';

      if (step.type === 'start') {
        badgeColor = 'bg-emerald-100 text-emerald-900 border-emerald-300';
        iconHtml = '<i data-lucide="play" class="w-4 h-4 text-emerald-700"></i>';
      } else if (step.type === 'destination') {
        badgeColor = 'bg-rose-100 text-rose-900 border-rose-300';
        iconHtml = '<i data-lucide="map-pin" class="w-4 h-4 text-rose-600"></i>';
      } else if (step.type === 'vertical') {
        badgeColor = 'bg-indigo-100 text-indigo-900 border-indigo-300';
        iconHtml = step.transport === 'elevator' 
          ? '<i data-lucide="arrow-up-down" class="w-4 h-4 text-indigo-700"></i>' 
          : '<i data-lucide="trending-up" class="w-4 h-4 text-indigo-700"></i>';
      }

      card.innerHTML = `
        <div class="flex items-start gap-3">
          <div class="w-9 h-9 rounded-xl bg-slate-100 border border-slate-300 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform shadow-xs">
            ${iconHtml}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs sm:text-sm font-extrabold text-slate-950 group-hover:text-emerald-800 transition-colors truncate">สเต็ป ${step.stepNumber}: ${step.title}</span>
              <span class="px-2.5 py-0.5 rounded-md text-[11px] font-extrabold border ${badgeColor} shrink-0">ชั้น ${step.floor}</span>
            </div>
            <p class="text-xs sm:text-sm text-slate-700 mt-1 leading-relaxed font-medium">${step.detail}</p>
          </div>
        </div>
      `;

      card.onclick = () => {
        const nodes = route.nodes || [];
        const targetNode = nodes.find(n => n.id === step.nodeId);
        if (targetNode) {
          // Switch to the step's floor first so the marker is on the right map
          if (this.map.currentFloor !== targetNode.floor) {
            this.switchFloor(targetNode.floor);
          }
          // Re-render the floor route after switching, then highlight the point
          this.map.renderCurrentFloorRoute();
          this.map.clearFocusMarkers();
          this.map.focusOnPoint(targetNode.x, targetNode.y, 1.5);
        }
      };

      container.appendChild(card);
    });

    lucide.createIcons();
  }

  clearRoute() {
    this.currentRoute = null;
    this.map.clearRoute();
    document.getElementById('summaryDistance').textContent = '-- m';
    document.getElementById('summaryTime').textContent = '~-- นาที';
    document.getElementById('summarySteps').textContent = '0 ขั้นตอน';
    
    document.getElementById('timelineContainer').innerHTML = `
      <div class="text-center py-10 text-slate-500 space-y-2">
        <i data-lucide="map" class="w-10 h-10 mx-auto text-slate-400"></i>
        <p class="text-xs sm:text-sm font-semibold">เลือกจุดเริ่มต้นและปลายทางเพื่อดูขั้นตอนนำทาง</p>
      </div>
    `;
    this.updateFloorRouteGlow([]);
    lucide.createIcons();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.app = new AppController();
  lucide.createIcons();
});
