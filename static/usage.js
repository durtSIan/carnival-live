(() => {
  let busy = false;
  async function heartbeat() {
    if (document.visibilityState !== "visible" || busy) return;
    try {
      const sentKey = "carnivalLive.usageLastSent";
      if (Date.now() - Number(localStorage.getItem(sentKey) || 0) < 45000) return;
      let device = localStorage.getItem("carnivalLive.usageDevice");
      if (!/^[0-9a-f]{32}$/.test(device || "")) {
        device = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
        localStorage.setItem("carnivalLive.usageDevice", device);
      }
      busy = true;
      const response = await fetch("/usage/heartbeat", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({device}), cache: "no-store", credentials: "omit"
      });
      if (response.ok) localStorage.setItem(sentKey, String(Date.now()));
    } catch (_) {
      // Restricted browser storage or a failed connection must not affect scores.
    } finally { busy = false; }
  }
  heartbeat();
  setInterval(heartbeat, 60000);
  document.addEventListener("visibilitychange", heartbeat);
  window.addEventListener("online", heartbeat);
})();
