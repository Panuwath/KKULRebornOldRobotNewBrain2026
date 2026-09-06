/**
 * Zenbo Scenario Builder Application Logic
 */

(function() {
  'use strict';

  var compiler = window.ZenboScenarioCompiler;
  var schema = compiler ? compiler.DEFAULT_SCHEMA : null;
  var twinInstance = null;

  var currentDoc = {
    meta: {
      scenario_id: 'user-my-scenario',
      title: 'สถานการณ์ใหม่',
      description: 'คำอธิบายสถานการณ์',
      version: '1.0.0'
    },
    blocks: [
      {
        id: 'block-1',
        type: 'speak',
        params: {
          text: 'สวัสดีครับ ผมคือหุ่นยนต์บุ๊คกี้ ยินดีต้อนรับสู่สำนักหอสมุด มข. ครับ',
          face: 'HAPPY',
          voice: 'male_child',
          head: { yaw: 0, pitch: 10 },
          wheel_lights: { mode: 'breathing', color: '#00d031', brightness: 10 }
        }
      }
    ]
  };

  function init() {
    loadDraft();
    fetchSchema();
    setupTwinPreview();
    setupEventHandlers();
    render();
  }

  function fetchSchema() {
    fetch('/api/v1/scenario-builder/schema')
      .then(function(res) {
        if (res.ok) return res.json();
        throw new Error('Schema endpoint error');
      })
      .then(function(data) {
        schema = data;
        render();
      })
      .catch(function() {
        if (compiler) schema = compiler.DEFAULT_SCHEMA;
        render();
      });
  }

  function setupTwinPreview() {
    var container = document.getElementById('twin-preview-container');
    if (container && window.ZenboTwin3D) {
      twinInstance = window.ZenboTwin3D.init(container, {
        mode: 'preview',
        interactive: true
      });
      syncTwinWithActiveBlock();
    }
  }

  function syncTwinWithActiveBlock() {
    if (!twinInstance) return;
    if (currentDoc.blocks.length > 0) {
      var first = currentDoc.blocks[0];
      if (first.params) {
        twinInstance.setCommanded({
          face: first.params.face || 'DEFAULT_STILL',
          head: first.params.head || { yaw: 0, pitch: 0 },
          lights: first.params.wheel_lights || { mode: 'breathing', color: '#00d031' }
        });
      }
    }
  }

  function loadDraft() {
    try {
      var saved = localStorage.getItem('zenbo:scenario-draft');
      if (saved) {
        var parsed = JSON.parse(saved);
        if (parsed && parsed.meta && Array.isArray(parsed.blocks)) {
          currentDoc = parsed;
        }
      }
    } catch (e) {
      console.warn('Failed to load local draft:', e);
    }
  }

  function saveDraft() {
    try {
      localStorage.setItem('zenbo:scenario-draft', JSON.stringify(currentDoc));
    } catch (e) {
      console.warn('Failed to save local draft:', e);
    }
  }

  function render() {
    saveDraft();
    renderMeta();
    renderBlocks();
    renderCompilerStatus();
    syncTwinWithActiveBlock();
  }

  function renderMeta() {
    var idInput = document.getElementById('meta-id');
    var titleInput = document.getElementById('meta-title');
    var descInput = document.getElementById('meta-desc');

    if (idInput && document.activeElement !== idInput) idInput.value = currentDoc.meta.scenario_id || '';
    if (titleInput && document.activeElement !== titleInput) titleInput.value = currentDoc.meta.title || '';
    if (descInput && document.activeElement !== descInput) descInput.value = currentDoc.meta.description || '';
  }

  function renderCompilerStatus() {
    if (!compiler) return;
    var res = compiler.compile(currentDoc, schema);

    var badge = document.getElementById('risk-level-badge');
    var capsContainer = document.getElementById('capabilities-container');
    var errorsContainer = document.getElementById('compile-errors');
    var saveBtn = document.getElementById('btn-save-draft');

    if (badge) {
      badge.textContent = res.risk_level || 'L0';
      badge.className = 'px-2.5 py-0.5 rounded-full text-xs font-mono font-bold ' +
        (res.risk_level === 'L0' || res.risk_level === 'L1' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40' :
         res.risk_level === 'L2' || res.risk_level === 'L3' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' :
         'bg-purple-500/20 text-purple-400 border border-purple-500/40');
    }

    if (capsContainer) {
      var caps = res.required_capabilities || ['SPEAK'];
      capsContainer.innerHTML = caps.map(function(c) {
        return '<span class="bg-slate-800 border border-slate-700 text-slate-300 text-[10px] px-2 py-0.5 rounded-md">' + c + '</span>';
      }).join(' ');
    }

    if (errorsContainer) {
      if (!res.ok && res.errors.length > 0) {
        errorsContainer.innerHTML = res.errors.map(function(e) {
          return '<div class="text-rose-400 text-xs flex items-center gap-1.5"><i class="fa-solid fa-triangle-exclamation"></i><span>' + escapeHtml(e.message_th) + '</span></div>';
        }).join('');
        errorsContainer.style.display = 'block';
      } else {
        errorsContainer.innerHTML = '';
        errorsContainer.style.display = 'none';
      }
    }

    // Role & Web environment check for Save button
    var isWeb = window.ZenboCommon ? window.ZenboCommon.isStandardWeb() : true;
    var canSave = window.ZenboCommon ? window.ZenboCommon.canPerform('operator') : true;

    if (saveBtn) {
      if (!isWeb) {
        saveBtn.disabled = true;
        saveBtn.title = 'บันทึกได้บน Web Console เท่านั้น (บน LINE กรุณาคัดลอก JSON)';
        saveBtn.className = 'px-4 py-2 bg-slate-800 text-slate-500 rounded-lg text-xs font-semibold cursor-not-allowed border border-slate-700';
      } else if (!canSave || !res.ok) {
        saveBtn.disabled = true;
        saveBtn.title = !canSave ? 'สิทธิ์ไม่เพียงพอ (ต้องเป็น Operator หรือ Admin)' : 'กรุณาแก้ไขข้อผิดพลาดก่อนบันทึก';
        saveBtn.className = 'px-4 py-2 bg-slate-800 text-slate-500 rounded-lg text-xs font-semibold cursor-not-allowed border border-slate-700';
      } else {
        saveBtn.disabled = false;
        saveBtn.title = 'บันทึกสถานการณ์ร่างลงสู่ระบบ';
        saveBtn.className = 'px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-semibold shadow-lg shadow-cyan-900/30 transition-all active:scale-95';
      }
    }
  }

  function renderBlocks() {
    var container = document.getElementById('builder-blocks-list');
    if (!container) return;

    if (currentDoc.blocks.length === 0) {
      container.innerHTML = '<div class="p-8 text-center text-slate-500 border-2 border-dashed border-slate-800 rounded-xl">' +
        '<i class="fa-solid fa-puzzle-piece text-3xl mb-2 text-slate-600"></i>' +
        '<p class="text-sm">ยังไม่มีขั้นตอนคำสั่ง เลือกบล็อกด้านล่างเพื่อเริ่มต้น</p></div>';
      return;
    }

    var html = '';
    for (var i = 0; i < currentDoc.blocks.length; i++) {
      var blk = currentDoc.blocks[i];
      html += renderBlockCard(blk, i);
    }
    container.innerHTML = html;
  }

  function renderBlockCard(blk, index) {
    var p = blk.params || {};
    var isFirst = index === 0;
    var isLast = index === currentDoc.blocks.length - 1;

    var badgeColor = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
    var blockTitle = 'พูดข้อความ';
    var icon = 'fa-solid fa-comment-dots';

    if (blk.type === 'vision_gate') {
      badgeColor = 'bg-amber-500/20 text-amber-300 border-amber-500/40';
      blockTitle = 'ตรวจจับ Vision Gate';
      icon = 'fa-solid fa-eye';
    } else if (blk.type === 'open_display') {
      badgeColor = 'bg-purple-500/20 text-purple-300 border-purple-500/40';
      blockTitle = 'แสดงหน้าจอ (Display)';
      icon = 'fa-solid fa-display';
    }

    var card = '<div class="builder-block-card zenbo-glass-card rounded-xl p-4 mb-3 border border-slate-700/60" data-block-id="' + blk.id + '">' +
      '<div class="flex items-center justify-between mb-3">' +
      '<div class="flex items-center gap-2">' +
      '<span class="w-6 h-6 rounded-full bg-slate-800 border border-slate-700 text-slate-300 text-xs font-mono font-bold flex items-center justify-center">' + (index + 1) + '</span>' +
      '<span class="px-2 py-0.5 rounded text-[11px] font-semibold border flex items-center gap-1.5 ' + badgeColor + '">' +
      '<i class="' + icon + '"></i>' + blockTitle + '</span>' +
      '</div>' +
      '<div class="flex items-center gap-1">' +
      '<button class="btn-move-up p-1.5 text-slate-400 hover:text-slate-200 disabled:opacity-30" data-idx="' + index + '" ' + (isFirst ? 'disabled' : '') + ' title="เลื่อนขึ้น"><i class="fa-solid fa-chevron-up text-xs"></i></button>' +
      '<button class="btn-move-down p-1.5 text-slate-400 hover:text-slate-200 disabled:opacity-30" data-idx="' + index + '" ' + (isLast ? 'disabled' : '') + ' title="เลื่อนลง"><i class="fa-solid fa-chevron-down text-xs"></i></button>' +
      '<button class="btn-delete-block p-1.5 text-rose-400 hover:text-rose-300 ml-1" data-idx="' + index + '" title="ลบขั้นตอนนี้"><i class="fa-solid fa-trash text-xs"></i></button>' +
      '</div></div>';

    // Body by block type
    if (blk.type === 'speak') {
      card += '<div class="space-y-3">' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">ข้อความพูดภาษาไทย</label>' +
        '<textarea class="block-param-text w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:border-cyan-500 focus:outline-none" rows="2" data-idx="' + index + '">' + escapeHtml(p.text || '') + '</textarea></div>' +
        '<div class="grid grid-cols-2 gap-2">' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">ใบหน้า (Expression)</label>' +
        renderFaceSelect(p.face || 'DEFAULT_STILL', index) + '</div>' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">เสียง (Voice Profile)</label>' +
        renderVoiceSelect(p.voice || 'male_child', index) + '</div></div>' +
        '</div>';
    } else if (blk.type === 'vision_gate') {
      card += '<div class="space-y-3">' +
        '<div class="grid grid-cols-2 gap-2">' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">ประเภทการตรวจจับ</label>' +
        '<select class="block-param-action w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" data-idx="' + index + '">' +
        '<option value="detect_face" ' + (p.action === 'detect_face' ? 'selected' : '') + '>ตรวจจับใบหน้า (Detect Face)</option>' +
        '<option value="detect_person" ' + (p.action === 'detect_person' ? 'selected' : '') + '>ตรวจจับบุคคล (Detect Person)</option>' +
        '<option value="gesture_point" ' + (p.action === 'gesture_point' ? 'selected' : '') + '>ตรวจจับการชี้นิ้ว (Gesture Point)</option>' +
        '</select></div>' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">เวลารอ (Timeout ms)</label>' +
        '<input type="number" class="block-param-timeout w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" value="' + (p.timeout_ms || 10000) + '" step="1000" data-idx="' + index + '"/></div></div>' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">ข้อความเมื่อตรวจพบ</label>' +
        '<input type="text" class="block-param-ondetect w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" value="' + escapeHtml(p.on_detect_text || 'ยินดีต้อนรับครับ') + '" data-idx="' + index + '"/></div>' +
        '<div><label class="text-[11px] text-slate-400 block mb-1">ข้อความเมื่อหมดเวลา</label>' +
        '<input type="text" class="block-param-ontimeout w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" value="' + escapeHtml(p.on_timeout_text || 'ขออภัยครับ ไม่พบใคร') + '" data-idx="' + index + '"/></div>' +
        '</div>';
    } else if (blk.type === 'open_display') {
      card += '<div class="space-y-2">' +
        '<label class="text-[11px] text-slate-400 block">URL หน้าเว็บห้องสมุด</label>' +
        '<select class="block-param-url w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" data-idx="' + index + '">' +
        '<option value="https://lib.kku.ac.th" ' + (p.url === 'https://lib.kku.ac.th' ? 'selected' : '') + '>https://lib.kku.ac.th (หน้าแรก)</option>' +
        '<option value="https://libn.kku.ac.th" ' + (p.url === 'https://libn.kku.ac.th' ? 'selected' : '') + '>https://libn.kku.ac.th (KKU Library Portal)</option>' +
        '<option value="https://library.kku.ac.th" ' + (p.url === 'https://library.kku.ac.th' ? 'selected' : '') + '>https://library.kku.ac.th (สำนักหอสมุด)</option>' +
        '</select></div>';
    }

    card += '</div>';
    return card;
  }

  function renderFaceSelect(currentFace, index) {
    var faces = (schema && schema.faces) || ['DEFAULT_STILL', 'HAPPY', 'PLEASED', 'PROUD', 'CONFIDENT', 'INTERESTED', 'EXPECTING', 'SERIOUS', 'SINGING'];
    var html = '<select class="block-param-face w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" data-idx="' + index + '">';
    for (var i = 0; i < faces.length; i++) {
      var f = typeof faces[i] === 'string' ? faces[i] : faces[i].id;
      html += '<option value="' + f + '" ' + (f === currentFace ? 'selected' : '') + '>' + f + '</option>';
    }
    html += '</select>';
    return html;
  }

  function renderVoiceSelect(currentVoice, index) {
    var voices = (schema && schema.voice_profiles) || [
      { id: 'male_child', label: 'เด็กชาย' },
      { id: 'female_sweet', label: 'ผู้หญิงหวาน' }
    ];
    var html = '<select class="block-param-voice w-full bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-xs text-slate-200" data-idx="' + index + '">';
    for (var i = 0; i < voices.length; i++) {
      var v = voices[i];
      html += '<option value="' + v.id + '" ' + (v.id === currentVoice ? 'selected' : '') + '>' + v.label + '</option>';
    }
    html += '</select>';
    return html;
  }

  function setupEventHandlers() {
    // Meta inputs
    var idInput = document.getElementById('meta-id');
    var titleInput = document.getElementById('meta-title');
    var descInput = document.getElementById('meta-desc');

    if (idInput) idInput.addEventListener('input', function(e) {
      currentDoc.meta.scenario_id = e.target.value.trim();
      renderCompilerStatus();
      saveDraft();
    });
    if (titleInput) titleInput.addEventListener('input', function(e) {
      currentDoc.meta.title = e.target.value;
      renderCompilerStatus();
      saveDraft();
    });
    if (descInput) descInput.addEventListener('input', function(e) {
      currentDoc.meta.description = e.target.value;
      saveDraft();
    });

    // Palette Add buttons
    document.querySelectorAll('.btn-add-block').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var type = btn.getAttribute('data-type');
        addBlock(type);
      });
    });

    // Delegated Block list actions
    var blockList = document.getElementById('builder-blocks-list');
    if (blockList) {
      blockList.addEventListener('input', handleBlockParamInput);
      blockList.addEventListener('change', handleBlockParamInput);
      blockList.addEventListener('click', handleBlockActionClick);
    }

    // Modal and Action bar buttons
    var btnViewJson = document.getElementById('btn-view-json');
    var btnCopyJson = document.getElementById('btn-copy-json');
    var btnDownloadJson = document.getElementById('btn-download-json');
    var btnSaveDraft = document.getElementById('btn-save-draft');
    var btnCloseModal = document.getElementById('btn-close-modal');

    if (btnViewJson) btnViewJson.addEventListener('click', openJsonModal);
    if (btnCloseModal) btnCloseModal.addEventListener('click', closeJsonModal);
    if (btnCopyJson) btnCopyJson.addEventListener('click', copyJsonToClipboard);
    if (btnDownloadJson) btnDownloadJson.addEventListener('click', downloadJsonFile);
    if (btnSaveDraft) btnSaveDraft.addEventListener('click', submitScenarioDraft);
  }

  function addBlock(type) {
    var newId = 'block-' + Date.now();
    var blk = { id: newId, type: type, params: {} };
    if (type === 'speak') {
      blk.params = { text: 'ข้อความใหม่ครับ', face: 'HAPPY', voice: 'male_child' };
    } else if (type === 'vision_gate') {
      blk.params = { action: 'detect_face', interval_ms: 1000, timeout_ms: 10000, on_detect_text: 'ยินดีต้อนรับครับ', on_timeout_text: 'ไม่พบใคร' };
    } else if (type === 'open_display') {
      blk.params = { url: 'https://lib.kku.ac.th' };
    }
    currentDoc.blocks.push(blk);
    render();
  }

  function handleBlockActionClick(e) {
    var btn = e.target.closest('button');
    if (!btn) return;
    var idx = parseInt(btn.getAttribute('data-idx'), 10);
    if (isNaN(idx)) return;

    if (btn.classList.contains('btn-delete-block')) {
      currentDoc.blocks.splice(idx, 1);
      render();
    } else if (btn.classList.contains('btn-move-up') && idx > 0) {
      var tmp = currentDoc.blocks[idx];
      currentDoc.blocks[idx] = currentDoc.blocks[idx - 1];
      currentDoc.blocks[idx - 1] = tmp;
      render();
    } else if (btn.classList.contains('btn-move-down') && idx < currentDoc.blocks.length - 1) {
      var tmp2 = currentDoc.blocks[idx];
      currentDoc.blocks[idx] = currentDoc.blocks[idx + 1];
      currentDoc.blocks[idx + 1] = tmp2;
      render();
    }
  }

  function handleBlockParamInput(e) {
    var el = e.target;
    var idx = parseInt(el.getAttribute('data-idx'), 10);
    if (isNaN(idx) || !currentDoc.blocks[idx]) return;
    var p = currentDoc.blocks[idx].params || {};

    if (el.classList.contains('block-param-text')) {
      p.text = el.value;
    } else if (el.classList.contains('block-param-face')) {
      p.face = el.value;
    } else if (el.classList.contains('block-param-voice')) {
      p.voice = el.value;
    } else if (el.classList.contains('block-param-action')) {
      p.action = el.value;
    } else if (el.classList.contains('block-param-timeout')) {
      p.timeout_ms = parseInt(el.value, 10);
    } else if (el.classList.contains('block-param-ondetect')) {
      p.on_detect_text = el.value;
    } else if (el.classList.contains('block-param-ontimeout')) {
      p.on_timeout_text = el.value;
    } else if (el.classList.contains('block-param-url')) {
      p.url = el.value;
    }

    currentDoc.blocks[idx].params = p;
    renderCompilerStatus();
    saveDraft();
    syncTwinWithActiveBlock();
  }

  function getCompiledOutput() {
    if (!compiler) return { ok: false };
    return compiler.compile(currentDoc, schema);
  }

  function openJsonModal() {
    var res = getCompiledOutput();
    var modal = document.getElementById('json-modal');
    var codeArea = document.getElementById('json-preview-code');
    if (modal && codeArea) {
      codeArea.textContent = JSON.stringify(res.request || res, null, 2);
      modal.classList.remove('hidden');
    }
  }

  function closeJsonModal() {
    var modal = document.getElementById('json-modal');
    if (modal) modal.classList.add('hidden');
  }

  function copyJsonToClipboard() {
    var res = getCompiledOutput();
    var str = JSON.stringify(res.request || res, null, 2);
    navigator.clipboard.writeText(str).then(function() {
      showToast('คัดลอก JSON เรียบร้อยแล้ว');
    }).catch(function() {
      showToast('ไม่สามารถคัดลอกได้');
    });
  }

  function downloadJsonFile() {
    var res = getCompiledOutput();
    var str = JSON.stringify(res.request || res, null, 2);
    var blob = new Blob([str], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (currentDoc.meta.scenario_id || 'scenario') + '.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  function submitScenarioDraft() {
    var res = getCompiledOutput();
    if (!res.ok) {
      showToast('กรุณาแก้ไขข้อผิดพลาดก่อนบันทึก');
      return;
    }

    var btn = document.getElementById('btn-save-draft');
    if (btn) btn.disabled = true;

    fetch('/api/v1/scenario-drafts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(res.request)
    })
      .then(function(r) {
        if (r.ok) return r.json();
        return r.json().then(function(err) { throw err; });
      })
      .then(function(data) {
        showToast('บันทึกสถานการณ์ร่างสำเร็จ (' + data.id + ')');
        var testLink = document.getElementById('test-scenario-link');
        if (testLink) {
          testLink.href = '/liff/scenarios/?scenario_id=' + encodeURIComponent(data.id);
          testLink.classList.remove('hidden');
        }
      })
      .catch(function(err) {
        var msg = (err.detail && err.detail.message) ? err.detail.message : 'บันทึกไม่สำเร็จ';
        showToast(msg);
      })
      .finally(function() {
        if (btn) btn.disabled = false;
      });
  }

  function showToast(msg) {
    var toast = document.getElementById('builder-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'builder-toast';
      toast.className = 'fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-slate-800 border border-slate-700 text-white text-xs px-4 py-2 rounded-lg shadow-xl';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.display = 'block';
    setTimeout(function() { toast.style.display = 'none'; }, 3000);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
