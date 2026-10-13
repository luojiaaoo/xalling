import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const compiled = ts.transpileModule(
  readFileSync(new URL("../src/api/http.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText;

function environment(fetch) {
  const window = new EventTarget();
  window.location = new URL("http://127.0.0.1:12345/");
  const timers = new Map();
  const reports = [];
  let openEvents;
  let closing = false;
  class TransportDisconnectedError extends Error {}
  const eventsReady = new Promise((resolve) => { openEvents = resolve; });
  const api = {};
  runInNewContext(compiled, {
    exports: api, window, URL, AbortController, TypeError, fetch,
    require: (module) => module === "./apiMessage"
      ? { notifyApiError: (...args) => reports.push(args) }
      : { connectEvents: () => eventsReady, connectionToken: () => "credential", isClosing: () => closing, TransportDisconnectedError },
    setTimeout: (callback) => { const handle = {}; timers.set(handle, callback); return handle; },
    clearTimeout: (handle) => timers.delete(handle),
  });
  return { api, window, timers, reports, openEvents, setClosing: (value) => { closing = value; }, TransportDisconnectedError };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("HTTP waits for events, authenticates and encodes typed parameters", async () => {
  const calls = [];
  const env = environment(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ content: "done" }) };
  });
  const result = env.api.request("POST", "/api/chat/messages", {
    body: { prompt: "hello" }, query: { project_path: "D:/中文目录", include_completed: false, absent: null },
  });
  assert.equal(calls.length, 0);
  env.openEvents();
  assert.equal((await result).content, "done");
  assert.equal(calls.length, 1);
  const { url, options } = calls[0];
  assert.equal(url.origin, env.window.location.origin);
  assert.equal(url.searchParams.get("project_path"), "D:/中文目录");
  assert.equal(url.searchParams.get("include_completed"), "false");
  assert.equal(url.searchParams.has("absent"), false);
  assert.equal(options.credentials, "same-origin");
  assert.equal(options.headers.Authorization, "Bearer credential");
  assert.equal(options.method, "POST");
  assert.deepEqual(JSON.parse(options.body), { prompt: "hello" });
  assert.equal(env.timers.size, 0);
});

test("validation and backend errors reach callers, silent logging avoids recursion", async () => {
  const env = environment(async () => ({
    ok: false, status: 422, json: async () => ({ detail: [{ msg: "invalid session" }, { msg: "invalid prompt" }] }),
  }));
  env.openEvents();
  await assert.rejects(env.api.request("POST", "/api/chat/messages"), /invalid session；invalid prompt/);
  assert.equal(env.reports.length, 1);
  await assert.rejects(env.api.request("POST", "/api/logs/frontend", { silent: true }), /invalid session/);
  assert.equal(env.reports.length, 1);
  assert.equal(env.timers.size, 0);
});

test("event disconnect aborts in-flight HTTP writes without repeating them", async () => {
  let calls = 0;
  const env = environment((_url, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  });
  env.openEvents();
  const result = env.api.request("POST", "/api/chat/messages", { body: { prompt: "hello" } });
  const rejection = assert.rejects(result, env.TransportDisconnectedError);
  await tick();
  env.window.dispatchEvent(new Event("xalling:transport-disconnected"));
  await rejection;
  assert.equal(calls, 1);
  assert.equal(env.timers.size, 0);
});

test("request timeout aborts transport and clears its timer", async () => {
  const env = environment((_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason));
  }));
  env.openEvents();
  const result = env.api.request("GET", "/api/theme");
  const rejection = assert.rejects(result, /响应超时/);
  await tick();
  [...env.timers.values()][0]();
  await rejection;
  assert.equal(env.timers.size, 0);
});

test("shutdown request survives unload and does not wait for the event connection", async () => {
  let finish, signal, keepalive;
  const env = environment((_url, options) => {
    signal = options.signal;
    keepalive = options.keepalive;
    return new Promise((resolve) => { finish = resolve; });
  });
  env.setClosing(true);
  const close = env.api.request("POST", "/api/window/close");
  assert.equal(keepalive, true);
  env.window.dispatchEvent(new Event("xalling:transport-disconnected"));
  env.window.dispatchEvent(new Event("beforeunload"));
  assert.equal(signal.aborted, false);
  finish({ ok: true, json: async () => ({ closing: true }) });
  assert.equal((await close).closing, true);
  assert.equal(env.timers.size, 0);
  assert.equal(env.reports.length, 0);
});

test("closing suppresses notifications for pending and newly requested work", async () => {
  let calls = 0;
  const env = environment((_url, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  });
  env.openEvents();
  const pending = env.api.request("GET", "/api/chat/sessions");
  const rejection = assert.rejects(pending, /应用正在关闭/);
  await tick();
  env.setClosing(true);
  env.window.dispatchEvent(new Event("beforeunload"));
  await rejection;
  await assert.rejects(env.api.request("GET", "/api/chat/sessions/session/context"), /应用正在关闭/);
  assert.equal(calls, 1);
  assert.equal(env.reports.length, 0);
});
