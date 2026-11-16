// Run with node tests/test_score_refresh.js.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function test() {
  let now = 0, calls = 0, updates = 0, failureMarker = false;
  let network = "unavailable";
  const timers = new Map();
  const events = {};
  const feed = {
    innerHTML: "old scores", hasAttribute: () => false, removeAttribute() {},
    replaceChildren(markup) { this.innerHTML = markup; }
  };
  const status = {hidden: true};
  const document = {
    visibilityState: "visible",
    getElementById: id => ({"score-feed": feed, "score-connection": status})[id],
    addEventListener: (name, fn) => { events[name] = fn; },
    dispatchEvent: () => { updates++; }
  };
  const url = "https://example.test/?grade_id=fixture";
  vm.runInNewContext(fs.readFileSync("static/score-refresh.js", "utf8"), {
    document, window: {addEventListener: document.addEventListener}, location: {href: url},
    Date: {now: () => now}, Event, AbortController,
    setTimeout: (fn, delay) => { const id = Symbol(); timers.set(id, {fn, delay}); return id; },
    clearTimeout: id => timers.delete(id),
    fetch: async (path, options) => {
      calls++;
      assert.equal(path, url);
      assert.equal(options.cache, "no-store");
      if (network === "unavailable") throw new Error("network lost returning from camera");
      return {ok: true, text: async () => "new scores"};
    },
    DOMParser: class {
      parseFromString(html) {
        return {getElementById: () => ({innerHTML: html, childNodes: [html], hasAttribute: () => failureMarker})};
      }
    }
  });
  async function tick(expectedDelay) {
    assert.equal(timers.size, 1);
    const [id, {fn, delay}] = timers.entries().next().value;
    assert.equal(delay, expectedDelay);
    timers.delete(id);
    now += delay;
    await fn();
  }

  document.visibilityState = "hidden";
  events.visibilitychange();
  now += 40000;
  assert.equal(timers.size, 0);
  assert.equal(calls, 0);
  document.visibilityState = "visible";
  events.visibilitychange();
  await tick(1000);
  assert.equal(feed.innerHTML, "old scores");
  assert.equal(status.hidden, false);
  network = "available";
  failureMarker = true;
  await tick(5000);
  assert.equal(feed.innerHTML, "old scores");
  assert.equal(status.hidden, false);
  failureMarker = false;
  await tick(10000); // Recover even when the phone doesn't emit an online event.
  assert.equal(feed.innerHTML, "new scores");
  assert.equal(status.hidden, true);
  assert.equal(updates, 1);
  await tick(30000);
  assert.equal(updates, 1);
}

test().then(() => console.log("Background pause, retry and score recovery passed"))
  .catch(error => { console.error(error); process.exitCode = 1; });
