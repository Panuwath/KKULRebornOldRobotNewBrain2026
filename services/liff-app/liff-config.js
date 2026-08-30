/*
 * The primary LIFF app launches the controller in Full mode.  The same ID is
 * used as a safe fallback for its child views until they need separate sizes.
 */
window.ZENBO_LIFF_CONFIG = {
  requireLogin: true,
  // A non-generic prefix prevents the campus reverse proxy from treating the
  // controller's API calls as n8n API traffic.
  apiBase: "/liff-api",
  defaultLiffId: "2011332417-AXUhnyrQ",
  liffIds: {
    "/liff/": "2011332417-AXUhnyrQ",
    "/liff/control/": "",
    "/liff/command/": "",
    "/liff/history/": "",
    "/liff/navigation/": "",
    "/liff/present/": ""
  },
  getLiffId(pathname) {
    const normalizedPath = pathname.endsWith("/") ? pathname : `${pathname}/`;
    const entries = Object.entries(this.liffIds)
      .sort(([left], [right]) => right.length - left.length);
    const match = entries.find(([path]) => normalizedPath.startsWith(path));
    return (match && match[1]) || this.defaultLiffId || "";
  }
};
