/**
 * KKUL Smart Search & Room Picker Controller
 * High-Legibility Typography & 2-Step Floor-First Selection
 */

class SmartSearchController {
  constructor() {
    this.modal = document.getElementById('searchModal');
    this.input = document.getElementById('modalSearchInput');
    this.resultsList = document.getElementById('searchResultsList');
    this.btnStartMode = document.getElementById('targetModeStart');
    this.btnDestMode = document.getElementById('targetModeDest');
    this.btnClear = document.getElementById('btnClearSearchInput');
    this.countText = document.getElementById('searchResultCountText');
    this.floorIndicator = document.getElementById('selectedFloorIndicator');

    this.roomsData = [];
    this.currentMode = 'dest'; // 'start' or 'dest'
    this.currentFloor = 'all'; // 'all', 1, 2, 3, 4, 5, 6
    this.currentCategory = 'all';

    this.init();
  }

  async init() {
    await this.fetchRooms();
    this.bindEvents();
  }

  async fetchRooms() {
    try {
      const res = await fetch('api/rooms');
      const data = await res.json();
      if (data.success) {
        this.roomsData = data.data;
      }
    } catch (err) {
      console.error('Failed to load rooms:', err);
    }
  }

  bindEvents() {
    // Open Modal Triggers
    const btnSelectStart = document.getElementById('btnSelectStart');
    if (btnSelectStart) btnSelectStart.addEventListener('click', () => {
      this.openModal('start');
    });

    const btnSelectDest = document.getElementById('btnSelectDestination');
    if (btnSelectDest) btnSelectDest.addEventListener('click', () => {
      this.openModal('dest');
    });

    const btnOpenSearch = document.getElementById('btnOpenSearchHeader');
    if (btnOpenSearch) btnOpenSearch.addEventListener('click', () => {
      this.openModal('dest');
    });

    // Close Modal Trigger
    const btnCloseModal = document.getElementById('btnCloseSearchModal');
    if (btnCloseModal) btnCloseModal.addEventListener('click', () => {
      this.closeModal();
    });

    // Close on Click Outside
    if (this.modal) this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.closeModal();
    });

    // Search Input
    if (this.input) this.input.addEventListener('input', (e) => {
      const query = e.target.value.trim();
      if (query.length > 0) {
        this.btnClear.classList.remove('hidden');
      } else {
        this.btnClear.classList.add('hidden');
      }
      this.renderResults(query, this.currentCategory, this.currentFloor);
    });

    // Clear Search Input Button
    if (this.btnClear) this.btnClear.addEventListener('click', () => {
      this.input.value = '';
      this.btnClear.classList.add('hidden');
      this.renderResults('', this.currentCategory, this.currentFloor);
      this.input.focus();
    });

    // Mode Switch (Start vs Dest)
    if (this.btnStartMode) this.btnStartMode.addEventListener('click', () => this.setMode('start'));
    if (this.btnDestMode) this.btnDestMode.addEventListener('click', () => this.setMode('dest'));

    // STEP 1: Floor Selector Tabs
    const floorTabs = document.querySelectorAll('.modal-floor-tab');
    floorTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const floorVal = tab.getAttribute('data-floor');
        this.setFloorFilter(floorVal);
      });
    });

    // STEP 2: Category Filter Chips
    const chips = document.querySelectorAll('.chip-filter');
    chips.forEach(chip => {
      chip.addEventListener('click', () => {
        chips.forEach(c => {
          c.classList.remove('active', 'bg-emerald-100', 'text-emerald-900', 'border-emerald-300');
          c.classList.add('bg-white', 'text-slate-800', 'border-slate-300');
        });
        chip.classList.add('active', 'bg-emerald-100', 'text-emerald-900', 'border-emerald-300');
        chip.classList.remove('bg-white', 'text-slate-800', 'border-slate-300');

        this.currentCategory = chip.getAttribute('data-cat');
        this.renderResults(this.input.value.trim(), this.currentCategory, this.currentFloor);
      });
    });

    // Keyboard Shortcuts (Ctrl + K / Cmd + K / Esc)
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        this.openModal('dest');
      } else if (e.key === 'Escape' && !this.modal.classList.contains('hidden')) {
        this.closeModal();
      }
    });
  }

  setFloorFilter(floorVal) {
    this.currentFloor = floorVal === 'all' ? 'all' : parseInt(floorVal);

    // Update Tab UI Styles
    const floorTabs = document.querySelectorAll('.modal-floor-tab');
    floorTabs.forEach(t => {
      const f = t.getAttribute('data-floor');
      if (f === String(floorVal)) {
        t.className = 'modal-floor-tab active px-4 py-1.5 rounded-xl bg-emerald-600 text-white font-extrabold text-xs shrink-0 shadow-xs border border-emerald-600 transition-all';
      } else {
        t.className = 'modal-floor-tab px-3.5 py-1.5 rounded-xl bg-white hover:bg-slate-100 text-slate-800 font-bold text-xs shrink-0 border border-slate-300 transition-all';
      }
    });

    // Update Indicator text
    if (this.floorIndicator) {
      if (this.currentFloor === 'all') {
        this.floorIndicator.textContent = 'แสดงทุกชั้น';
        this.floorIndicator.className = 'text-xs text-emerald-800 font-extrabold';
      } else {
        this.floorIndicator.textContent = `กรองเฉพาะ ชั้น ${this.currentFloor}`;
        this.floorIndicator.className = 'text-xs text-emerald-900 font-extrabold px-2.5 py-0.5 rounded-lg bg-emerald-100 border border-emerald-300';
      }
    }

    this.renderResults(this.input.value.trim(), this.currentCategory, this.currentFloor);
  }

  setMode(mode) {
    this.currentMode = mode;
    if (mode === 'start') {
      this.btnStartMode.className = 'px-3.5 py-1.5 rounded-lg bg-emerald-600 text-white font-extrabold shadow-xs transition-all';
      this.btnDestMode.className = 'px-3.5 py-1.5 rounded-lg text-slate-700 hover:text-slate-950 font-bold transition-all';
    } else {
      this.btnDestMode.className = 'px-3.5 py-1.5 rounded-lg bg-emerald-600 text-white font-extrabold shadow-xs transition-all';
      this.btnStartMode.className = 'px-3.5 py-1.5 rounded-lg text-slate-700 hover:text-slate-950 font-bold transition-all';
    }
  }

  openModal(mode = 'dest', initialFloor = null) {
    this.setMode(mode);
    this.modal.classList.remove('hidden');
    this.input.value = '';
    this.btnClear.classList.add('hidden');
    
    if (initialFloor !== null) {
      this.setFloorFilter(initialFloor);
    } else if (window.app && window.app.map && window.app.map.currentFloor) {
      this.setFloorFilter(window.app.map.currentFloor);
    } else {
      this.setFloorFilter('all');
    }

    setTimeout(() => this.input.focus(), 100);
  }

  closeModal() {
    this.modal.classList.add('hidden');
  }

  renderResults(query = '', category = 'all', floorFilter = 'all') {
    let filtered = this.roomsData;

    // 1. Filter by Floor
    if (floorFilter !== 'all') {
      filtered = filtered.filter(r => r.floor === parseInt(floorFilter));
    }

    // 2. Filter by Category
    if (category && category !== 'all') {
      filtered = filtered.filter(r => r.category === category || r.type === category);
    }

    // 3. Filter by Text Query
    if (query) {
      const q = query.toLowerCase();
      filtered = filtered.filter(r => {
        const th = (r.name_th || '').toLowerCase().includes(q);
        const en = (r.name_en || '').toLowerCase().includes(q);
        const code = (r.code || '').toLowerCase().includes(q);
        const kw = r.keywords && r.keywords.some(k => k.toLowerCase().includes(q));
        return th || en || code || kw;
      });
    }

    this.countText.textContent = `พบ ${filtered.length} รายการ ${floorFilter !== 'all' ? `(บนชั้น ${floorFilter})` : ''}`;
    this.resultsList.innerHTML = '';

    if (filtered.length === 0) {
      this.resultsList.innerHTML = `
        <div class="text-center py-12 text-slate-500 space-y-2">
          <i data-lucide="search-x" class="w-10 h-10 mx-auto text-slate-400"></i>
          <p class="text-sm font-bold text-slate-700">ไม่พบผลการค้นหาบน ${floorFilter !== 'all' ? `ชั้น ${floorFilter}` : 'ทุกชั้น'}</p>
          <p class="text-xs text-slate-500">ลองเปลี่ยนชั้น หรือกดปุ่ม "🏢 ทุกชั้น" ด้านบน</p>
        </div>
      `;
      lucide.createIcons();
      return;
    }

    const floorColorBadges = {
      1: 'bg-emerald-100 text-emerald-900 border-emerald-300',
      2: 'bg-teal-100 text-teal-900 border-teal-300',
      3: 'bg-sky-100 text-sky-900 border-sky-300',
      4: 'bg-indigo-100 text-indigo-900 border-indigo-300',
      5: 'bg-purple-100 text-purple-900 border-purple-300',
      6: 'bg-rose-100 text-rose-900 border-rose-300'
    };

    filtered.forEach(room => {
      const item = document.createElement('div');
      item.className = 'group p-3.5 rounded-2xl bg-white hover:bg-emerald-50 border border-slate-300 hover:border-emerald-500 transition-all flex items-center justify-between gap-3 cursor-pointer shadow-xs';
      
      const badgeStyle = floorColorBadges[room.floor] || 'bg-slate-100 text-slate-800 border-slate-300';

      item.innerHTML = `
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div class="w-10 h-10 rounded-xl bg-slate-100 group-hover:bg-emerald-100 flex items-center justify-center shrink-0 border border-slate-300 group-hover:border-emerald-400 transition-colors">
            <i data-lucide="${this.getRoomIcon(room.type, room.category)}" class="w-5 h-5 text-emerald-700"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-sm font-extrabold text-slate-950 group-hover:text-emerald-800 transition-colors truncate">${room.name_th}</span>
              ${room.code ? `<span class="px-2 py-0.5 rounded bg-slate-100 text-[11px] font-mono text-slate-700 font-bold border border-slate-300">${room.code}</span>` : ''}
            </div>
            <p class="text-xs text-slate-600 truncate mt-0.5 font-medium">${room.name_en || room.description || ''}</p>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <span class="px-2.5 py-1 rounded-lg text-xs font-extrabold border ${badgeStyle}">ชั้น ${room.floor}</span>
          <button class="px-4 py-2 rounded-xl bg-emerald-600 group-hover:bg-emerald-700 text-white font-extrabold text-xs shadow-xs transition-colors">
            เลือก
          </button>
        </div>
      `;

      item.onclick = () => {
        if (this.currentMode === 'start') {
          window.app.setStart(room);
        } else {
          window.app.setDestination(room);
        }
        this.closeModal();
      };

      this.resultsList.appendChild(item);
    });

    lucide.createIcons();
  }

  getRoomIcon(type, category) {
    if (type === 'restroom' || category === 'restroom') return 'toilet';
    if (type === 'stairs') return 'trending-up';
    if (type === 'elevator') return 'arrow-up-down';
    if (type === 'entrance') return 'door-open';
    if (category === 'cafe') return 'coffee';
    if (category === 'meeting') return 'users';
    if (category === 'learning') return 'book-open';
    if (category === 'service') return 'info';
    return 'map-pin';
  }
}

window.SmartSearchController = SmartSearchController;
