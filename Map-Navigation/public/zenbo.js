/**
 * KKUL Zenbo Robot Kiosk Controller with Integrated Interactive Map & URL Query Support
 */

let mapEngine = null;
let currentRouteData = null;
let currentStepIdx = 0;

document.addEventListener('DOMContentLoaded', () => {
  // Initialize Map Engine for Zenbo Screen
  mapEngine = new InteractiveMapEngine({
    initialFloor: 2
  });

  lucide.createIcons();

  // Floor Buttons inside Zenbo view
  const floorBtns = document.querySelectorAll('#zenboFloorButtonGroup .floor-btn');
  floorBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const floor = parseInt(btn.getAttribute('data-floor'));
      switchZenboFloor(floor);
    });
  });

  // Step Navigation Buttons inside Zenbo Follow-Me Card
  const btnZenboNext = document.getElementById('btnZenboNext');
  if (btnZenboNext) btnZenboNext.addEventListener('click', () => {
    if (currentRouteData && currentStepIdx < currentRouteData.instructions.length - 1) {
      currentStepIdx++;
      updateZenboStepView();
    } else {
      finishNavigation();
    }
  });

  const btnZenboPrev = document.getElementById('btnZenboPrev');
  if (btnZenboPrev) btnZenboPrev.addEventListener('click', () => {
    if (currentRouteData && currentStepIdx > 0) {
      currentStepIdx--;
      updateZenboStepView();
    }
  });

  const btnZenboCancel = document.getElementById('btnZenboCancel');
  if (btnZenboCancel) btnZenboCancel.addEventListener('click', () => {
    cancelNavigation();
  });

  // Collapsible Sidebar Toggle (◀ / ☰)
  const sidebar = document.getElementById('zenboSidebar');
  const btnCollapse = document.getElementById('btnCollapseSidebar');
  const btnExpand = document.getElementById('btnExpandSidebar');
  let sidebarCollapsed = false;

  function toggleZenboSidebar(forceState = null) {
    sidebarCollapsed = forceState !== null ? forceState : !sidebarCollapsed;
    if (sidebarCollapsed) {
      sidebar.classList.add('hidden');
      btnExpand.classList.remove('hidden');
      btnExpand.classList.add('flex');
    } else {
      sidebar.classList.remove('hidden');
      btnExpand.classList.add('hidden');
      btnExpand.classList.remove('flex');
    }
    lucide.createIcons();
  }

  if (btnCollapse) btnCollapse.addEventListener('click', () => toggleZenboSidebar(true));
  if (btnExpand) btnExpand.addEventListener('click', () => toggleZenboSidebar(false));
  // Expose global API for Zenbo robot webview
  window.zenboToggleSidebar = toggleZenboSidebar;

  // Check URL Query Parameters (e.g. ?from=1102&to=1401 or ?to=ห้องน้ำ)
  const urlParams = new URLSearchParams(window.location.search);
  const fromQuery = urlParams.get('from');
  const toQuery = urlParams.get('to');
  const autoStart = urlParams.get('autostart');

  if (toQuery) {
    navigateWithParams(fromQuery || 'poi_f2_main_entrance', toQuery, autoStart === 'true');
  }
});

async function navigateWithParams(fromParam, toParam, shouldAutoStart = true) {
  try {
    const res = await fetch(`api/zenbo/navigate?from=${encodeURIComponent(fromParam)}&to=${encodeURIComponent(toParam)}`);
    const data = await res.json();

    if (data.success) {
      currentRouteData = {
        destination: data.destination,
        start: data.start,
        totalDistanceMeters: data.total_distance_meters,
        estimatedMinutes: data.estimated_minutes,
        passedFloors: data.passed_floors,
        speech_text: data.speech_text,
        step_speeches: data.step_speeches,
        instructions: data.instructions,
        nodes: data.nodes,
        pathSteps: data.path_steps
      };
      currentStepIdx = 0;

      // Switch to start floor
      switchZenboFloor(data.start.floor);
      mapEngine.setRoute(currentRouteData);
      updateFloorGlow(data.passed_floors);

      if (shouldAutoStart) {
        startZenboNavigation();
      }
    }
  } catch (err) {
    console.error('Failed to load navigation from URL params:', err);
  }
}

function switchZenboFloor(floorNumber) {
  document.querySelectorAll('#zenboFloorButtonGroup .floor-btn').forEach(b => {
    const f = parseInt(b.getAttribute('data-floor'));
    if (f === floorNumber) {
      b.classList.add('active-floor');
    } else {
      b.classList.remove('active-floor');
    }
  });

  mapEngine.switchFloor(floorNumber);
}

// Quick destination handler
async function zenboGoTo(type) {
  const startId = "poi_f2_main_entrance"; // Default robot dock at Floor 2 Main Entrance

  let url = '';
  if (type === 'toilet') {
    url = `api/zenbo/navigate?from=${startId}&to=ห้องน้ำ`;
  } else if (type === 'cafe') {
    url = `api/zenbo/navigate?from=${startId}&to=r3200`;
  } else if (type === 'circ') {
    url = `api/zenbo/navigate?from=${startId}&to=r3206`;
  } else if (type === 'ai') {
    url = `api/zenbo/navigate?from=${startId}&to=r3202`;
  } else if (type === 'baisri') {
    url = `api/zenbo/navigate?from=${startId}&to=1401`;
  } else if (type === 'prod') {
    url = `api/zenbo/navigate?from=${startId}&to=1300`;
  }

  try {
    const res = await fetch(url);
    const data = await res.json();

    if (data.success) {
      currentRouteData = {
        destination: data.destination,
        start: data.start,
        totalDistanceMeters: data.total_distance_meters,
        estimatedMinutes: data.estimated_minutes,
        passedFloors: data.passed_floors,
        speech_text: data.speech_text,
        step_speeches: data.step_speeches,
        instructions: data.instructions,
        nodes: data.nodes,
        pathSteps: data.path_steps
      };
      currentStepIdx = 0;
      
      switchZenboFloor(data.start.floor);
      mapEngine.setRoute(currentRouteData);
      updateFloorGlow(currentRouteData.passedFloors);
      
      startZenboNavigation();
    }
  } catch (err) {
    console.error('Zenbo routing failed:', err);
  }
}

function updateFloorGlow(passedFloors = []) {
  document.querySelectorAll('#zenboFloorButtonGroup .floor-btn').forEach(btn => {
    const f = parseInt(btn.getAttribute('data-floor'));
    if (passedFloors.includes(f)) {
      btn.classList.add('in-route');
    } else {
      btn.classList.remove('in-route');
    }
  });
}

function startZenboNavigation() {
  document.getElementById('zenboQuickGrid').classList.add('hidden');
  document.getElementById('zenboNavCard').classList.remove('hidden');

  const destName = currentRouteData.destination.name_th;
  document.getElementById('zenboStatusBadge').textContent = 'กำลังนำทาง...';
  document.getElementById('zenboSpeechText').textContent = `"กำลังนำทางไปที่ ${destName} กรุณาเดินตาม Zenbo นะครับ"`;
  document.getElementById('zenboSubText').textContent = `ระยะทางรวม ${currentRouteData.totalDistanceMeters} เมตร (~${currentRouteData.estimatedMinutes} นาที)`;

  updateZenboStepView();
}

function updateZenboStepView() {
  const steps = currentRouteData.instructions;
  const step = steps[currentStepIdx];

  document.getElementById('zenboStepIndicator').textContent = `ขั้นตอนที่ ${step.stepNumber} จาก ${steps.length}`;
  document.getElementById('zenboFloorBadge').textContent = `ชั้น ${step.floor}`;
  document.getElementById('zenboStepTitle').textContent = step.title;
  document.getElementById('zenboStepDetail').textContent = step.detail;

  const btnNext = document.getElementById('btnZenboNext');
  if (currentStepIdx === steps.length - 1) {
    btnNext.textContent = '✔ ถึงจุดหมายแล้ว';
    btnNext.className = 'flex-1 py-2 rounded-xl bg-emerald-400 text-slate-950 font-extrabold text-sm shadow-md';
  } else {
    btnNext.textContent = 'ถัดไป ▶';
    btnNext.className = 'flex-1 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-extrabold text-sm shadow-md';
  }

  // Switch map floor if step is on another floor
  if (mapEngine.currentFloor !== step.floor) {
    switchZenboFloor(step.floor);
  }

  // Focus map on step node
  const targetNode = currentRouteData.nodes.find(n => n.id === step.nodeId);
  if (targetNode) {
    mapEngine.focusOnPoint(targetNode.x, targetNode.y, 1.4);
  }

  lucide.createIcons();
}

function finishNavigation() {
  document.getElementById('zenboStatusBadge').textContent = 'ถึงจุดหมายเรียบร้อยแล้ว';
  document.getElementById('zenboSpeechText').textContent = `"ถึงจุดหมายเรียบร้อยแล้วครับ! มีอะไรให้ Zenbo ช่วยเหลือเพิ่มเติมไหมครับ?"`;
  document.getElementById('zenboSubText').textContent = 'แตะที่ปุ่มด้านล่างเพื่อเลือกบริการอื่น';

  setTimeout(() => {
    cancelNavigation();
  }, 4000);
}

function cancelNavigation() {
  currentRouteData = null;
  currentStepIdx = 0;
  if (mapEngine) mapEngine.clearRoute();
  updateFloorGlow([]);

  document.getElementById('zenboNavCard').classList.add('hidden');
  document.getElementById('zenboQuickGrid').classList.remove('hidden');
  document.getElementById('zenboStatusBadge').textContent = 'ZENBO พร้อมนำทาง';
  document.getElementById('zenboSpeechText').textContent = `"สวัสดีครับ ต้องการให้ Zenbo พาไปที่ไหนดีครับ?"`;
  document.getElementById('zenboSubText').textContent = 'แตะปุ่มสัมผัสด้านล่าง หรือดูเส้นทางบนแผนที่ด้านขวาได้ทันที';
}

// Global API for Zenbo Robot Webview Integration
window.zenboSwitchFloor = switchZenboFloor;
window.zenboNextStep = () => {
  const btn = document.getElementById('btnZenboNext');
  if (btn) btn.click();
};
window.zenboPrevStep = () => {
  const btn = document.getElementById('btnZenboPrev');
  if (btn) btn.click();
};
