/**
 * Shared helpers for the Zenbo web controller.
 *
 * Works on both the LINE LIFF host (LINE identity) and the normal web host
 * (OIDC-backed sessions managed by the Core API).
 */
(function () {
  const STANDARD_WEB_HOST = "lib.kku.ac.th";
  const ROBOT_KEY = "zenbo:selectedRobot";

  function isStandardWeb() {
    return window.location.hostname.toLowerCase() === STANDARD_WEB_HOST;
  }

  function currentPath() {
    return window.location.pathname + window.location.search;
  }

  function loginPageUrl() {
    return "/liff/login/?next=" + encodeURIComponent(currentPath());
  }

  function oidcLoginUrl() {
    return "/api/v1/web-auth/oidc/login?next=" + encodeURIComponent(currentPath());
  }

  async function fetchMe() {
    try {
      const res = await fetch("/api/v1/web-auth/me", { credentials: "same-origin" });
      return { ok: res.ok, status: res.status, data: res.ok ? await res.json() : null };
    } catch (e) {
      return { ok: false, status: 0, data: null, error: e };
    }
  }

  /** Require authentication on standard web; redirect to login if no session. */
  async function ensureAuth() {
    const me = await fetchMe();
    if (!me.ok && isStandardWeb()) {
      window.location.href = loginPageUrl();
      return null;
    }
    currentUser = me.ok && me.data ? me.data.user : null;
    return currentUser;
  }

  function oidcLogin() {
    window.location.href = oidcLoginUrl();
  }

  async function logout() {
    try {
      await fetch("/api/v1/web-auth/logout", { method: "POST", credentials: "same-origin" });
    } catch (e) {
      console.warn("Logout error:", e);
    }
    currentUser = null;
    window.location.href = "/liff/login/?logged_out=1";
  }

  /**
   * Fetch wrapper that redirects standard web users to login on 401.
   */
  async function api(path, options) {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    const res = await fetch(path, opts);
    if (res.status === 401) {
      if (isStandardWeb()) {
        window.location.href = loginPageUrl();
        return null;
      }
      currentUser = null;
      renderUserBar();
      applyRoleGating();
      throw new Error("unauthorized");
    }
    return res;
  }

  function loadRobotSelection() {
    try {
      return localStorage.getItem(ROBOT_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function saveRobotSelection(slug) {
    try {
      if (slug) localStorage.setItem(ROBOT_KEY, slug);
    } catch (e) {
      // ignore private-mode storage errors
    }
  }

  function haptic() {
    if (window.navigator && window.navigator.vibrate) {
      window.navigator.vibrate(12);
    }
  }

  function stopLabel() {
    return "หยุดฉุกเฉิน";
  }

  function formatRole(role) {
    const map = {
      admin: "ผู้ดูแลระบบ",
      operator: "ผู้ควบคุม",
      viewer: "ผู้ชม",
    };
    return map[(role || "").toLowerCase()] || role || "ผู้ใช้";
  }

  const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };
  let currentUser = null;

  async function refreshUser() {
    if (currentUser) return currentUser;
    const me = await fetchMe();
    currentUser = me.ok && me.data ? me.data.user : null;
    return currentUser;
  }

  function getRole() {
    return (currentUser && currentUser.role) || "viewer";
  }

  function roleRank(role) {
    return ROLE_RANK[(role || "").toLowerCase()] ?? 0;
  }

  function canPerform(requiredRole) {
    return roleRank(getRole()) >= roleRank(requiredRole || "viewer");
  }

  /**
   * Disable or hide elements marked with data-require-role="operator|admin".
   * Viewers can still use emergency stop and robot selection; operators keep
   * drive/speak but cannot access admin-only toggles such as APK update or
   * scenario import.
   */
  function applyRoleGating(container) {
    const scope = container || document.body;
    if (!scope) return;
    const userRole = getRole();
    scope.querySelectorAll("[data-require-role]").forEach((el) => {
      const required = el.dataset.requireRole;
      const allowed = canPerform(required);
      const targets = (el.matches("button, input, select, textarea, a")) ? [el] : el.querySelectorAll("button, input, select, textarea, a");
      targets.forEach((target) => {
        target.disabled = !allowed;
        target.setAttribute("aria-disabled", String(!allowed));
        if (!allowed) {
          target.classList.add("opacity-50", "cursor-not-allowed");
          target.title = target.title || `ต้องมีสิทธิ์ ${formatRole(required)}`;
        } else {
          target.classList.remove("opacity-50", "cursor-not-allowed");
        }
      });
    });
    scope.querySelectorAll("[data-hide-for-role]").forEach((el) => {
      const hiddenRoles = (el.dataset.hideForRole || "").split(/\s+/);
      el.hidden = hiddenRoles.includes(userRole.toLowerCase());
    });
  }

  function updateNavMenuItems() {
    const user = currentUser;
    document.querySelectorAll("nav[aria-label='เครื่องมือเพิ่มเติม'], nav[aria-label='เมนู Control']").forEach((nav) => {
      const existingAuthLink = nav.querySelector(".auth-menu-link");
      if (existingAuthLink) existingAuthLink.remove();
      const authLink = document.createElement("a");
      authLink.className = "auth-menu-link rounded-lg px-3 py-2 text-xs font-semibold hover:bg-slate-700 flex items-center";
      if (user) {
        authLink.href = "javascript:ZenboCommon.logout()";
        authLink.innerHTML = `<i class="fa-solid fa-right-from-bracket mr-2 text-red-400"></i><span class="text-red-300">ออกจากระบบ</span>`;
      } else {
        authLink.href = loginPageUrl();
        authLink.innerHTML = `<i class="fa-solid fa-right-to-bracket mr-2 text-emerald-400"></i><span class="text-emerald-300">เข้าสู่ระบบ</span>`;
      }
      nav.appendChild(authLink);
    });
  }

  function renderUserBar(containerId) {
    const user = currentUser;
    updateNavMenuItems();
    const target = containerId ? document.getElementById(containerId) : document.getElementById("user-profile-bar");
    if (!target) return;
    if (!user) {
      if (isStandardWeb()) {
        target.innerHTML = `<a href="${loginPageUrl()}" class="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800/90 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:border-emerald-400 hover:text-white transition shadow"><i class="fa-solid fa-right-to-bracket text-emerald-400"></i> เข้าสู่ระบบ</a>`;
      } else {
        target.innerHTML = '';
      }
      return;
    }
    const roleColors = {
      admin: "bg-red-950/80 text-red-300 border-red-700/60",
      operator: "bg-blue-950/80 text-blue-300 border-blue-700/60",
      viewer: "bg-slate-800 text-slate-300 border-slate-600"
    };
    const badgeClass = roleColors[(user.role || "").toLowerCase()] || roleColors.viewer;
    const safeName = String(user.display_name || user.username || "ผู้ใช้").replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    target.innerHTML = `
      <div class="flex items-center gap-2">
        <span class="inline-flex items-center gap-1.5 rounded-full border ${badgeClass} px-3 py-1 text-xs font-semibold shadow-sm">
          <i class="fa-solid fa-circle-user text-emerald-400"></i> ${safeName} (${formatRole(user.role)})
        </span>
        <button type="button" onclick="ZenboCommon.logout()" class="inline-flex items-center gap-1.5 rounded-xl border border-red-500/40 bg-red-950/50 px-3 py-1 text-xs font-semibold text-red-200 hover:bg-red-900/60 hover:text-white transition shadow" title="ออกจากระบบ">
          <i class="fa-solid fa-right-from-bracket"></i> ออกจากระบบ
        </button>
      </div>
    `;
  }

  window.ZenboCommon = {
    isStandardWeb,
    fetchMe,
    ensureAuth,
    loginPageUrl,
    oidcLogin,
    logout,
    api,
    loadRobotSelection,
    saveRobotSelection,
    haptic,
    stopLabel,
    formatRole,
    refreshUser,
    getRole,
    canPerform,
    applyRoleGating,
    renderUserBar,
  };
})();
