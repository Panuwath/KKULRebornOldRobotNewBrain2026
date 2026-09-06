/**
 * Zenbo SDK Action IDs & RobotFace Catalog
 * Source of truth: com.asus.robotframework.API.Utility$PlayAction & RobotFace
 * Extracted from ZenboJuniorSDK.jar
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ZenboActions = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var ACTIONS = [
    // --- Dance & Music ---
    { id: 22, name: 'Body_twist_1', title: 'บิดตัวส่ายเอว 1', category: 'dance', icon: '🕺', desc: 'บิดลำตัวส่ายเอวจังหวะ 1' },
    { id: 23, name: 'Body_twist_2', title: 'บิดตัวส่ายเอว 2', category: 'dance', icon: '💃', desc: 'บิดลำตัวส่ายเอวจังหวะ 2' },
    { id: 15, name: 'Dance_b_1_loop', title: 'เต้นเร็ว B1 (Loop)', category: 'dance', icon: '🎶', desc: 'เต้นวนลูปจังหวะเร็ว B1' },
    { id: 21, name: 'Dance_s_1_loop', title: 'เต้นช้า S1 (Loop)', category: 'dance', icon: '🎵', desc: 'เต้นวนลูปจังหวะช้า S1' },
    { id: 24, name: 'Dance_2_loop', title: 'เต้นแบบ 2 (Loop)', category: 'dance', icon: '🎊', desc: 'เต้นสไตล์ที่ 2 วนลูป' },
    { id: 27, name: 'Dance_3_loop', title: 'เต้นแบบ 3 (Loop)', category: 'dance', icon: '🎉', desc: 'เต้นสไตล์ที่ 3 วนลูป' },
    { id: 17, name: 'Music_1_loop', title: 'โยกตามดนตรี 1 (Loop)', category: 'dance', icon: '🎹', desc: 'โยกตัวตามจังหวะดนตรีวนลูป' },

    // --- Nod & Head Shakes ---
    { id: 2, name: 'Nod_1', title: 'พยักหน้าตอบรับ', category: 'head', icon: '🙇', desc: 'พยักหน้า 1 ครั้ง' },
    { id: 5, name: 'Shake_head_1', title: 'ส่ายหน้าปฏิเสธ 1', category: 'head', icon: '🙅', desc: 'ส่ายหน้าปฏิเสธเบาๆ' },
    { id: 11, name: 'Shake_head_2', title: 'ส่ายหน้าปฏิเสธ 2', category: 'head', icon: '🤷', desc: 'ส่ายหน้าปฏิเสธชัดเจน' },
    { id: 20, name: 'Shake_head_3', title: 'ส่ายหน้า 3', category: 'head', icon: '😐', desc: 'ส่ายหน้าจังหวะปานกลาง' },
    { id: 25, name: 'Shake_head_4_loop', title: 'ส่ายหน้าวนลูป', category: 'head', icon: '🔄', desc: 'ส่ายหน้าต่อเนื่องหลายครั้ง' },
    { id: 26, name: 'Head_twist_1_loop', title: 'เอียงคอสงสัย (Loop)', category: 'head', icon: '🤔', desc: 'เอียงคอสลับซ้ายขวาอย่างสงสัย' },
    { id: 28, name: 'Shake_head_5', title: 'ส่ายหน้าเร็ว 5', category: 'head', icon: '🤨', desc: 'ส่ายหน้าเร็วแบบเอะใจ' },
    { id: 42, name: 'Shake_head_6', title: 'ส่ายหน้าช้า 6', category: 'head', icon: '🧐', desc: 'ส่ายหน้าช้าๆ แบบครุ่นคิด' },

    // --- Head Pitch (Up & Down) ---
    { id: 3, name: 'Head_up_1', title: 'เงยหน้ามองขึ้น 1', category: 'pitch', icon: '⬆️', desc: 'เงยหน้ามุมปกติ' },
    { id: 4, name: 'Head_up_2', title: 'เงยหน้ามองขึ้น 2', category: 'pitch', icon: '🔼', desc: 'เงยหน้ามุมปานกลาง' },
    { id: 6, name: 'Head_up_3', title: 'เงยหน้ามองสูง 3', category: 'pitch', icon: '🔝', desc: 'เงยหน้ามองมุมสูง' },
    { id: 7, name: 'Head_up_4', title: 'เงยหน้าเร็ว 4', category: 'pitch', icon: '⏫', desc: 'เงยหน้าขึ้นอย่างรวดเร็ว' },
    { id: 13, name: 'Head_up_5', title: 'เงยหน้าระดับ 5', category: 'pitch', icon: '🔺', desc: 'เงยหน้าองศาระดับ 5' },
    { id: 54, name: 'Head_up_6', title: 'เงยหน้าระดับ 6', category: 'pitch', icon: '📐', desc: 'เงยหน้าองศาระดับ 6' },
    { id: 16, name: 'Head_up_7', title: 'เงยหน้ามองฟ้า 7', category: 'pitch', icon: '🔭', desc: 'เงยหน้าสุดมุมมองเพดาน' },
    { id: 8, name: 'Head_down_1', title: 'ก้มหน้าลง 1', category: 'pitch', icon: '⬇️', desc: 'ก้มหน้ามุมมองต่ำ 1' },
    { id: 9, name: 'Head_down_2', title: 'ก้มหน้าลง 2', category: 'pitch', icon: '🔽', desc: 'ก้มหน้ามุมมองต่ำ 2' },
    { id: 10, name: 'Head_down_3', title: 'ก้มหน้าลง 3', category: 'pitch', icon: '⏬', desc: 'ก้มหน้ามองล่างปานกลาง' },
    { id: 12, name: 'Head_down_4', title: 'ก้มหน้าระดับ 4', category: 'pitch', icon: '🔻', desc: 'ก้มหน้าองศาระดับ 4' },
    { id: 14, name: 'Head_down_5', title: 'ก้มหน้าระดับ 5', category: 'pitch', icon: '📉', desc: 'ก้มหน้าองศาระดับ 5' },
    { id: 43, name: 'Head_down_7', title: 'ก้มหน้ามองพื้น 7', category: 'pitch', icon: '👣', desc: 'ก้มหน้ามองพื้นระดับ 7' },

    // --- Turn Body & Rotation ---
    { id: 18, name: 'Turn_left_1', title: 'หันฐานไปซ้าย 1', category: 'turn', icon: '↩️', desc: 'หมุนฐานหุ่นไปทางซ้าย 1' },
    { id: 19, name: 'Turn_left_2', title: 'หันฐานไปซ้าย 2', category: 'turn', icon: '⬅️', desc: 'หมุนฐานหุ่นไปทางซ้าย 2' },
    { id: 44, name: 'Turn_right_1', title: 'หันฐานไปขวา 1', category: 'turn', icon: '↪️', desc: 'หมุนฐานหุ่นไปทางขวา 1' },
    { id: 45, name: 'Turn_right_2', title: 'หันฐานไปขวา 2', category: 'turn', icon: '➡️', desc: 'หมุนฐานหุ่นไปทางขวา 2' },
    { id: 46, name: 'Turn_left_reverse_1', title: 'หันซ้ายคืนกลับ 1', category: 'turn', icon: '🔁', desc: 'หมุนฐานซ้ายแล้วกลับที่เดิม' },
    { id: 47, name: 'Turn_right_reverse_1', title: 'หันขวาคืนกลับ 1', category: 'turn', icon: '🔂', desc: 'หมุนฐานขวาแล้วกลับที่เดิม' },
    { id: 48, name: 'Turn_left_reverse_2', title: 'หันซ้ายคืนกลับ 2', category: 'turn', icon: '🔄', desc: 'หมุนฐานซ้ายมุมกว้างแล้วกลับ' },
    { id: 49, name: 'Turn_right_reverse_2', title: 'หันขวาคืนกลับ 2', category: 'turn', icon: '🔃', desc: 'หมุนฐานขวามุมกว้างแล้วกลับ' },

    // --- Default & Vision ---
    { id: 0, name: 'Default_1', title: 'คืนท่าตั้งต้น 1', category: 'misc', icon: '🤖', desc: 'รีเซ็ตท่าทางสู่ตำแหน่งปกติ 1' },
    { id: 1, name: 'Default_2', title: 'คืนท่าตั้งต้น 2', category: 'misc', icon: '🧍', desc: 'รีเซ็ตท่าทางสู่ตำแหน่งปกติ 2' },
    { id: 1007, name: 'Find_face', title: 'สแกนหาใบหน้า', category: 'misc', icon: '👁️', desc: 'หมุนหัวสแกนหาใบหน้าผู้ใช้' }
  ];

  var FACES = [
    // เชิงบวก
    { id: 'HAPPY', title: 'มีความสุข', icon: '😄', desc: 'ยิ้มกว้าง สดใส', group: 'positive' },
    { id: 'PLEASED', title: 'พึงพอใจ', icon: '😊', desc: 'ยิ้มหวาน อ่อนโยน', group: 'positive' },
    { id: 'PROUD', title: 'ภาคภูมิใจ', icon: '😎', desc: 'เท่ มั่นใจ ภูมิใจ', group: 'positive' },
    { id: 'CONFIDENT', title: 'มั่นใจ', icon: '🤩', desc: 'ตาเป็นประกาย มั่นใจ', group: 'positive' },
    { id: 'ACTIVE', title: 'สดใสกระตือรือร้น', icon: '✨', desc: 'พร้อมลุย สดใส', group: 'positive' },
    { id: 'SINGING', title: 'ร้องเพลง', icon: '🎤', desc: 'อารมณ์ดี ร้องเพลง', group: 'positive' },

    // ตั้งใจ & สงสัย
    { id: 'INTERESTED', title: 'สนใจใคร่รู้', icon: '🧐', desc: 'สนใจ ใส่ใจผู้ฟัง', group: 'attentive' },
    { id: 'EXPECTING', title: 'ตั้งตารอ', icon: '🥺', desc: 'รอคอยอย่างกระตือรือร้น', group: 'attentive' },
    { id: 'DOUBT', title: 'สงสัยลังเล', icon: '🤔', desc: 'ครุ่นคิด สงสัย', group: 'attentive' },
    { id: 'QUESTIONING', title: 'ตั้งคำถาม', icon: '❓', desc: 'มีข้อสงสัย ตาโต', group: 'attentive' },

    // น่ารัก & เขิน
    { id: 'SHY', title: 'ขวยเขิน', icon: '😳', desc: 'แก้มแดง ขี้อาย', group: 'cute' },
    { id: 'INNOCENT', title: 'ไร้เดียงสา', icon: '😇', desc: 'ตาโต บริสุทธิ์น่ารัก', group: 'cute' },

    // อารมณ์อื่นๆ
    { id: 'SERIOUS', title: 'จริงจังสุภาพ', icon: '😐', desc: 'สุภาพ เรียบร้อย', group: 'other' },
    { id: 'SHOCK', title: 'ตกใจประหลาดใจ', icon: '😲', desc: 'ตาค้าง ตกใจ', group: 'other' },
    { id: 'WORRIED', title: 'เป็นห่วงกังวล', icon: '😟', desc: 'กังวล เป็นห่วง', group: 'other' },
    { id: 'HELPLESS', title: 'ช่วยไม่ได้', icon: '🤷', desc: 'ยอมรับ ปล่อยวาง', group: 'other' },
    { id: 'TIRED', title: 'เหนื่อยง่วง', icon: '😴', desc: 'ง่วงนอน พักสายตา', group: 'other' },
    { id: 'LAZY', title: 'ขี้เกียจ', icon: '🥱', desc: 'หาว ตาปรือ', group: 'other' },
    { id: 'IMPATIENT', title: 'รีบร้อนใจร้อน', icon: '⏳', desc: 'อยู่ไม่นิ่ง รอนาน', group: 'other' },
    { id: 'PRETENDING', title: 'ขี้เล่นกวนๆ', icon: '😜', desc: 'แลบลิ้น กวนๆ', group: 'other' },
    { id: 'AWARE_LEFT', title: 'มองทางซ้าย', icon: '👀', desc: 'ชำเลืองมองซ้าย', group: 'other' },
    { id: 'AWARE_RIGHT', title: 'มองทางขวา', icon: '👁️', desc: 'ชำเลืองมองขวา', group: 'other' },
    { id: 'DEFAULT', title: 'ปกติ (กะพริบตา)', icon: '🤖', desc: 'สแตนด์บาย กะพริบตา', group: 'system' },
    { id: 'DEFAULT_STILL', title: 'นิ่งสงบ', icon: '🧘', desc: 'นิ่ง ไม่กะพริบตา', group: 'system' },
    { id: 'HIDEFACE', title: 'ปิดหน้าจอ', icon: '⬛', desc: 'ดับหน้าจอ', group: 'system' }
  ];

  var CATEGORIES = [
    { id: 'all', title: 'ทั้งหมด', count: ACTIONS.length },
    { id: 'dance', title: 'เต้น & ดนตรี', icon: '🕺', count: ACTIONS.filter(function(a){return a.category==='dance';}).length },
    { id: 'head', title: 'พยักหน้า & ส่ายหน้า', icon: '🙇', count: ACTIONS.filter(function(a){return a.category==='head';}).length },
    { id: 'pitch', title: 'ก้มหน้า & เงยหน้า', icon: '⬆️', count: ACTIONS.filter(function(a){return a.category==='pitch';}).length },
    { id: 'turn', title: 'หันตัว & หมุนกลับ', icon: '🔄', count: ACTIONS.filter(function(a){return a.category==='turn';}).length },
    { id: 'misc', title: 'ท่าตั้งต้น & สแกน', icon: '🤖', count: ACTIONS.filter(function(a){return a.category==='misc';}).length }
  ];

  return {
    ACTIONS: ACTIONS,
    FACES: FACES,
    CATEGORIES: CATEGORIES,
    getActionById: function (id) {
      for (var i = 0; i < ACTIONS.length; i++) {
        if (ACTIONS[i].id === Number(id)) return ACTIONS[i];
      }
      return null;
    },
    getFaceById: function (id) {
      for (var i = 0; i < FACES.length; i++) {
        if (FACES[i].id === id) return FACES[i];
      }
      return null;
    },
    getActionsByCategory: function (category) {
      if (!category || category === 'all') return ACTIONS;
      return ACTIONS.filter(function (a) { return a.category === category; });
    }
  };
}));
