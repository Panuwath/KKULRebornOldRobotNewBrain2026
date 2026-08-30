(function () {
  const SDK_URL = 'https://static.line-scdn.net/liff/edge/2/sdk.js';
  const config = window.ZENBO_LIFF_CONFIG || {};

  const state = {
    ready: false,
    inClient: false,
    profile: null,
    context: null,
    liffId: '',
  };

  function loadSDK() {
    return new Promise((resolve, reject) => {
      if (window.liff) return resolve();
      const script = document.createElement('script');
      script.src = SDK_URL;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('LIFF SDK failed to load'));
      document.head.appendChild(script);
    });
  }

  async function init() {
    if (state.ready) return state;
    const liffId = typeof config.getLiffId === 'function'
      ? config.getLiffId(window.location.pathname)
      : (config.liffId || config.defaultLiffId || '');
    state.liffId = liffId;
    if (!liffId) {
      state.ready = true;
      return state;
    }
    try {
      await loadSDK();
      await window.liff.init({ liffId });
      state.inClient = window.liff.isInClient();
      if (!window.liff.isLoggedIn()) {
        if (config.requireLogin) {
          window.liff.login({ redirectUri: window.location.href });
          return state;
        }
      } else {
        state.profile = await window.liff.getProfile();
      }
      state.context = window.liff.getContext();
    } catch (error) {
      console.warn('LIFF init failed:', error);
    }
    state.ready = true;
    return state;
  }

  function identity() {
    if (!state.profile) return {};
    return {
      user_id: state.profile.userId || null,
      display_name: state.profile.displayName || null,
      picture_url: state.profile.pictureUrl || null,
    };
  }

  function isInClient() {
    return !!state.inClient;
  }

  function isLoggedIn() {
    return !!(window.liff && window.liff.isLoggedIn());
  }

  function getLiffId() {
    return state.liffId;
  }

  function login() {
    if (window.liff && state.ready) return window.liff.login();
    return Promise.resolve();
  }

  function sendMessages(messages) {
    if (!window.liff || !state.ready) return Promise.resolve();
    return window.liff.sendMessages(messages).catch(function () {});
  }

  function closeWindow() {
    if (window.liff && state.ready) window.liff.closeWindow();
  }

  window.ZenboLiff = {
    init: init,
    identity: identity,
    isInClient: isInClient,
    isLoggedIn: isLoggedIn,
    getLiffId: getLiffId,
    login: login,
    sendMessages: sendMessages,
    closeWindow: closeWindow,
    get state() { return state; }
  };
})();
