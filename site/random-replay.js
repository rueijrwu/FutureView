(() => {
  const API_ORIGIN = "https://futureview.rueijrwu.workers.dev";
  const TOKEN_KEY = "futureview_auth_token";
  const DEFAULT_REPLAY_TIME = "08:30";

  function showError(message = "") {
    const element = document.getElementById("error");
    if (element) element.textContent = message;
  }

  async function fetchRange(product) {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    if (!token) {
      location.replace("/login.html");
      return null;
    }
    const response = await fetch(`${API_ORIGIN}/api/replay/range?product=${encodeURIComponent(product)}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      location.replace("/login.html");
      return null;
    }
    let payload = null;
    try { payload = await response.json(); } catch {}
    if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
    return payload;
  }

  const button = document.getElementById("random-btn");
  if (!button) return;

  // app.js installs the legacy random handler first. Replacing the onclick property here
  // makes Random refresh authoritative range metadata on every click instead of reusing
  // the replayRangeInfo object captured when the page initially loaded.
  button.onclick = async (event) => {
    event?.preventDefault?.();
    if (button.disabled) return;
    button.disabled = true;
    try {
      showError();
      const product = document.getElementById("product")?.value || "MES";
      const info = await fetchRange(product);
      if (!info) return;
      const sessions = Array.isArray(info.sessions)
        ? info.sessions.filter((day) => /^\d{4}-\d{2}-\d{2}$/.test(String(day)))
        : [];
      if (!sessions.length) throw new Error("Replay session metadata is unavailable");
      const day = sessions[Math.floor(Math.random() * sessions.length)];
      const start = document.getElementById("start");
      if (!start) throw new Error("Replay start control is unavailable");
      start.value = `${day}T${DEFAULT_REPLAY_TIME}`;
      document.getElementById("start-btn")?.click();
    } catch (error) {
      showError(String(error?.message || error));
    } finally {
      // startReplay owns the disabled state while session creation is in flight.
      if (!document.getElementById("start-btn")?.disabled) button.disabled = false;
    }
  };
})();
