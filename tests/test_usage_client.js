// Run with node tests/test_usage_client.js. Exercise real heartbeat code without a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const code = fs.readFileSync("static/usage.js", "utf8");
const storage = new Map();
let now = 1000000, requests = 0, hidden = false, succeed = true;
async function page() {
  const events = {};
  const context = {
    Date: {now: () => now},
    crypto: require("node:crypto").webcrypto,
    Uint8Array,
    document: {get visibilityState() {return hidden ? "hidden" : "visible";},
      addEventListener: (event, callback) => events[event] = callback},
    window: {addEventListener: (event, callback) => events[event] = callback},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    setInterval: callback => events.interval = callback,
    fetch: async (url, options) => {
      assert.equal(url, "/usage/heartbeat");
      assert.equal(options.credentials, "omit");
      assert.match(JSON.parse(options.body).device, /^[a-f0-9]{32}$/);
      requests++;
      return {ok: succeed};
    }
  };
  vm.runInNewContext(code, context);
  await new Promise(resolve => setImmediate(resolve));
  return events;
}
(async () => {
  await page();
  assert.equal(requests, 1);
  const device = storage.get("carnivalLive.usageDevice");
  now += 30000;
  await page(); // Automatic 30-second page refresh does not double the heartbeat rate.
  assert.equal(requests, 1);
  now += 30000;
  const events = await page();
  assert.equal(requests, 2);
  await page(); // A second tab shares the same identifier and recent-heartbeat marker.
  assert.equal(requests, 2);
  assert.equal(storage.get("carnivalLive.usageDevice"), device);
  now += 60000;
  hidden = true;
  await events.interval();
  assert.equal(requests, 2);
  hidden = false;
  succeed = false;
  await events.visibilitychange();
  assert.equal(requests, 3);
  succeed = true;
  await events.online(); // A failed heartbeat can retry when connectivity returns.
  assert.equal(requests, 4);
  console.log("Heartbeat visibility, reload, multiple-tab and recovery checks passed");
})().catch(error => {console.error(error); process.exitCode = 1;});
