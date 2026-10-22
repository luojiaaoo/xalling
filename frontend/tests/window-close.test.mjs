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

test("desktop close requests backend shutdown and disconnects events after acknowledgement", async () => {
  let acknowledge;
  const env = environment((method, path, options) => {
    assert.equal(method, "POST");
    assert.equal(path, "/api/window/close");
    assert.equal(options.silent, false);
    return new Promise((resolve) => { acknowledge = resolve; });
  });
  const closed = env.api.closeWindow();
  assert.deepEqual(env.actions, []);
  assert.equal(env.isClosing(), true);
  acknowledge({ closing: true });
  await closed;
  assert.deepEqual(env.actions, ["events.close"]);
  assert.equal(env.isClosing(), true);
});

test("checkpoint preview uses the common API contract without exposing SDK wire fields", async () => {
  const env = environment(async (method, path, options) => {
    assert.equal(method, "POST");
    assert.equal(path, "/api/chat/files/rewind/preview");
    assert.deepEqual(JSON.parse(JSON.stringify(options.body)), { session_id: "session", checkpoint_id: "checkpoint" });
    return { can_restore: true, files: ["a.txt"], insertions: 0, deletions: 2 };
  });
  const preview = await env.api.previewChatFiles("session", "checkpoint");
  assert.equal(preview.can_restore, true);
  assert.deepEqual(preview.files, ["a.txt"]);
  assert.equal(preview.insertions, 0);
});

test("failed desktop close allows normal work and another close attempt", async () => {
  let requests = 0;
  const env = environment(async () => {
    if (++requests === 1) throw new Error("shutdown failed");
    return { closing: true };
  });
  await env.api.closeWindow();
  assert.deepEqual(env.actions, []);
  assert.equal(env.isClosing(), false);
  await env.api.closeWindow();
  assert.equal(requests, 2);
  assert.deepEqual(env.actions, ["events.close"]);
});

test("repeated close clicks create only one shutdown request", async () => {
  let acknowledge, requests = 0;
  const env = environment(() => {
    requests++;
    return new Promise((resolve) => { acknowledge = resolve; });
  });
  const first = env.api.closeWindow();
  const second = env.api.closeWindow();
  assert.equal(second, first);
  assert.equal(requests, 1);
  acknowledge({ closing: true });
  await first;
  await env.api.closeWindow();
  assert.equal(requests, 1);
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
    assert.deepEqual(env.actions, ["events.close"]);
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
