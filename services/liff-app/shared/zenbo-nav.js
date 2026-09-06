/**
 * Zenbo Navigation Component
 * Standardized Header and Bottom Navigation for all LIFF routes
 */

(function(window) {
  'use strict';

  var ITEMS = [
    { id: 'home', href: '/liff/', label: 'หน้าหลัก', icon: 'fa-solid fa-house', activeColor: 'text-cyan-400' },
    { id: 'control', href: '/liff/control/', label: 'จอยสติ๊ก', icon: 'fa-solid fa-gamepad', activeColor: 'text-indigo-400' },
    { id: 'scenario', href: '/liff/scenario/', label: 'สถานการณ์', icon: 'fa-solid fa-masks-theater', activeColor: 'text-purple-400' },
    { id: 'command', href: '/liff/command/', label: 'สั่งงาน AI', icon: 'fa-solid fa-wand-magic-sparkles', activeColor: 'text-amber-400' },
    { id: 'history', href: '/liff/history/', label: 'ประวัติ', icon: 'fa-solid fa-clock-rotate-left', activeColor: 'text-emerald-400' }
  ];

  function getActiveItemId(currentPath) {
    var path = currentPath || (window.location ? window.location.pathname : '/liff/');
    var matched = 'home';
    var maxLen = 0;
    for (var i = 0; i < ITEMS.length; i++) {
      var item = ITEMS[i];
      if (path.indexOf(item.href) === 0 && item.href.length > maxLen) {
        maxLen = item.href.length;
        matched = item.id;
      }
    }
    return matched;
  }

  function render(opts) {
    opts = opts || {};
    var mountBottom = opts.mountBottom;
    if (typeof mountBottom === 'string') {
      mountBottom = document.querySelector(mountBottom);
    }
    if (!mountBottom) {
      mountBottom = document.getElementById('zenbo-bottom-nav');
    }

    if (mountBottom) {
      var activeId = opts.active ? opts.active : getActiveItemId(opts.currentPath);
      var badges = opts.badges || {};

      var navHtml = '<nav class="fixed bottom-0 left-0 right-0 z-40 bg-slate-900/90 backdrop-blur-md border-t border-slate-700/60 pb-safe">' +
        '<div class="max-w-md mx-auto flex items-center justify-around py-2 px-1">';

      for (var i = 0; i < ITEMS.length; i++) {
        var it = ITEMS[i];
        var isActive = (it.id === activeId);
        var colorClass = isActive ? it.activeColor : 'text-slate-400 hover:text-slate-200';
        var badge = badges[it.id];
        var badgeHtml = badge ? '<span class="absolute -top-1 -right-2 bg-rose-500 text-white text-[9px] px-1 rounded-full">' + badge + '</span>' : '';

        navHtml += '<a href="' + it.href + '" class="relative flex flex-col items-center flex-1 py-1 transition-transform active:scale-95 ' + colorClass + '">' +
          '<i class="' + it.icon + ' text-base mb-0.5"></i>' +
          badgeHtml +
          '<span class="text-[10px] tracking-tight font-medium">' + it.label + '</span>' +
          (isActive ? '<span class="absolute -bottom-1 w-6 h-0.5 rounded-full bg-current"></span>' : '') +
          '</a>';
      }

      navHtml += '</div></nav>';
      mountBottom.innerHTML = navHtml;
    }
  }

  window.ZenboNav = {
    ITEMS: ITEMS,
    getActiveItemId: getActiveItemId,
    render: render
  };
})(typeof window !== 'undefined' ? window : this);
