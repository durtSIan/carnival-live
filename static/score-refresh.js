(() => {
  const feed = document.getElementById("score-feed");
  const status = document.getElementById("score-connection");
  if (!feed || !status) return;

  const interval = 30000;
  const settling = 1000;
  let lastSuccess = Date.now();
  let timer;
  let inFlight = false;
  let failures = 0;
  let previousMarkup = feed.innerHTML;

  function showRetry() {
    const message = "Trying to reconnect. Scores may be out of date.";
    if (status.textContent !== message) status.textContent = message;
    status.hidden = false;
  }

  function schedule(delay) {
    clearTimeout(timer);
    if (document.visibilityState === "visible" && !inFlight) {
      timer = setTimeout(refresh, delay);
    }
  }

  async function refresh() {
    if (inFlight || document.visibilityState !== "visible") return;
    inFlight = true;
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(location.href, {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw new Error("Score refresh failed");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const next = page.getElementById("score-feed");
      if (!next || next.hasAttribute("data-refresh-failed")) throw new Error("Scores unavailable");
      if (previousMarkup !== next.innerHTML) {
        previousMarkup = next.innerHTML;
        feed.replaceChildren(...next.childNodes);
        document.dispatchEvent(new Event("carnival:scores-updated"));
      }
      feed.removeAttribute("data-refresh-failed");
      lastSuccess = Date.now();
      failures = 0;
      status.hidden = true;
    } catch (_) {
      failures++;
      showRetry();
    } finally {
      clearTimeout(deadline);
      inFlight = false;
      schedule(failures ? Math.min(interval, 5000 * 2 ** Math.min(failures - 1, 3)) : interval);
    }
  }

  function resume() {
    const remaining = interval - (Date.now() - lastSuccess);
    schedule(failures ? settling : Math.max(settling, remaining));
  }

  document.addEventListener("visibilitychange", resume);
  window.addEventListener("pageshow", event => { if (event.persisted) resume(); });
  window.addEventListener("offline", () => {
    showRetry();
    schedule(5000);
  });
  window.addEventListener("online", () => {
    schedule(settling);
  });
  if (feed.hasAttribute("data-refresh-failed")) {
    failures = 1;
    showRetry();
  }
  schedule(failures ? 5000 : interval);
})();
