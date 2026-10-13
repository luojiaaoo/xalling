import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { typescriptLoader } from "./helpers/load-typescript.mjs";

function environment(request) {
  const actions = [];
  let closing = false;
  const window = new EventTarget();
  window.close = () => actions.push("tab.close");
  const load = typescriptLoader({
    globals: { window },
    overrides: {
      "./http": { request },
      "./websocket": {
        isClosing: () => closing,
        setClosing: (value) => { closing = value; },
        disconnectEvents: () => actions.push("events.close"),
      },
    },
  });
  return { actions, window, isClosing: () => closing, api: load(fileURLToPath(new URL("../src/api/client.ts", import.meta.url))) };
}

test("close marks the page closed immediately after acknowledgement without closing the tab", async () => {
  let acknowledge;
  const env = environment((method, path) => {
    assert.equal(method, "POST");
    assert.equal(path, "/api/window/close");
    return new Promise((resolve) => { acknowledge = resolve; });
  });
  const closed = env.api.closeWindow();
  assert.deepEqual(env.actions, []);
  assert.equal(env.isClosing(), true);
  assert.equal(env.api.getShutdownState().phase, "closing");
  acknowledge({ closing: true });
  await closed;
  assert.deepEqual(env.actions, ["events.close"]);
  assert.equal(env.api.getShutdownState().phase, "closed");
});

test("failed shutdown leaves the tab open to show the error", async () => {
  const env = environment(async () => { throw new Error("shutdown failed"); });
  await env.api.closeWindow();
  assert.deepEqual(env.actions, []);
  assert.equal(env.api.getShutdownState().phase, "failed");
  assert.equal(env.api.getShutdownState().error, "shutdown failed");
});

test("repeated close clicks create only one shutdown request", async () => {
  let acknowledge, requests = 0;
  const env = environment(() => {
    requests++;
    return new Promise((resolve) => { acknowledge = resolve; });
  });
  const first = env.api.closeWindow();
  await env.api.closeWindow();
  assert.equal(requests, 1);
  acknowledge({ closing: true });
  await first;
});

for (const event of ["pagehide", "unload"]) {
  test(`${event} starts shutdown without waiting for the page to stay open`, async () => {
    let acknowledge, requests = 0;
    const env = environment((method, path, options) => {
      requests++;
      assert.equal(method, "POST");
      assert.equal(path, "/api/window/close");
      assert.equal(options.silent, true);
      return new Promise((resolve) => { acknowledge = resolve; });
    });
    env.window.dispatchEvent(new Event(event));
    assert.equal(requests, 1);
    assert.equal(env.isClosing(), true);
    env.window.dispatchEvent(new Event("pagehide"));
    env.window.dispatchEvent(new Event("unload"));
    assert.equal(requests, 1);
    acknowledge({ closing: true });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(env.api.getShutdownState().phase, "closed");
    env.window.dispatchEvent(new Event("unload"));
    assert.equal(requests, 1);
  });
}

test("leaving during button shutdown reuses the pending close request", async () => {
  let acknowledge, requests = 0;
  const env = environment(() => {
    requests++;
    return new Promise((resolve) => { acknowledge = resolve; });
  });
  const pending = env.api.closeWindow();
  env.window.dispatchEvent(new Event("pagehide"));
  env.window.dispatchEvent(new Event("unload"));
  assert.equal(requests, 1);
  acknowledge({ closing: true });
  await pending;
});
