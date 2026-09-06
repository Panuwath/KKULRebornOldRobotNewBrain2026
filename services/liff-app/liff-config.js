/*
 * The primary LIFF app launches the controller in Full mode.  The same ID is
 * used by every child view so a normal browser uses the same LINE Login
 * session before it can operate a controller page.
 */
const standardWebHost = window.location.hostname.toLowerCase() === "lib.kku.ac.th";

window.ZENBO_LIFF_CONFIG = {
  // The public library route is a normal web controller, not a LINE LIFF
  // launch. Keep the existing LINE Login flow only on the LIFF host.
  requireLogin: !standardWebHost,
  // A non-generic prefix prevents the campus reverse proxy from treating the
  // controller's API calls as n8n API traffic.
  apiBase: "/liff-api",
  defaultLiffId: "2011332417-AXUhnyrQ",
  liffIds: {
    "/liff/": "2011332417-AXUhnyrQ",
    "/liff/control/": "2011332417-AXUhnyrQ",
    "/liff/command/": "2011332417-AXUhnyrQ",
    "/liff/history/": "2011332417-AXUhnyrQ",
    "/liff/navigation/": "2011332417-AXUhnyrQ",
    "/liff/autonomy/": "2011332417-AXUhnyrQ",
    "/liff/scenario/": "2011332417-AXUhnyrQ",
    "/liff/present/": "2011332417-AXUhnyrQ",
    "/liff/scenarios/": "2011332417-AXUhnyrQ"
  },
  getLiffId(pathname) {
    if (standardWebHost) return "";
    const normalizedPath = pathname.endsWith("/") ? pathname : `${pathname}/`;
    const entries = Object.entries(this.liffIds)
      .sort(([left], [right]) => right.length - left.length);
    const match = entries.find(([path]) => normalizedPath.startsWith(path));
    // Every controller view uses the primary LIFF ID. LINE reuses its
    // existing browser session, so a signed-in user is not asked twice.
    return match ? match[1] : (this.defaultLiffId || "");
  }
};
