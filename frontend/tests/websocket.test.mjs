import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/api/websocket.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function environment(hash = "#token=test-credential") {
  const window = new EventTarget();
  window.location = new URL(`http://127.0.0.1:12345/${hash}`);
  const stored = new Map();
  const timers = new Map();
  const sockets = [];
  const api = {};
  class Socket extends EventTarget {
    static OPEN = 1;
    readyState = 0;
    sent = [];
    constructor(url, protocols) {
      super();
      this.url = url;
      this.protocols = protocols;
      sockets.push(this);
    }
    open() {
      this.readyState = 1;
      this.dispatchEvent(new Event("open"));
    }
    send(data) {
      if (this.readyState !== 1) throw new Error("Socket closed");
      this.sent.push(JSON.parse(data));
    }
    receive(data) {
      const event = new Event("message");
      event.data = JSON.stringify(data);
      this.dispatchEvent(event);
    }
    close(code = 1006) {
      this.readyState = 3;
      const event = new Event("close");
      event.code = code;
      this.dispatchEvent(event);
    }
  }
  class CustomEvent extends Event {
    constructor(type, { detail }) {
      super(type);
      this.detail = detail;
    }
  }
  runInNewContext(compiled, {
    exports: api, window, WebSocket: Socket, URL, URLSearchParams, Event, CustomEvent,
    sessionStorage: { getItem: (key) => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) },
    history: { replaceState: (_state, _title, path) => { window.location = new URL(path, window.location); } },
    setTimeout: (callback, delay) => {
      const handle = {};
      timers.set(handle, { callback, delay });
      return handle;
    },
    clearTimeout: (handle) => timers.delete(handle),
  });
  return { api, window, sockets, stored, timers };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("event subscribers share one authenticated socket and hide launch credentials", async () => {
  const env = environment();
  const first = env.api.connectEvents();
  const second = env.api.connectEvents();
  assert.equal(env.sockets.length, 1);
  const socket = env.sockets[0];
  assert.equal(String(socket.url), "ws://127.0.0.1:12345/ws");
  assert.deepEqual(Array.from(socket.protocols), ["xalling", "auth.test-credential"]);
  assert.equal(env.window.location.hash, "");
  socket.open();
  await tick();
  assert.equal(socket.sent.length, 0);
  assert.equal(await first, socket);
  assert.equal(await second, socket);
  assert.equal(env.api.connectionToken(), "test-credential");
  env.window.dispatchEvent(new Event("beforeunload"));
  assert.equal(env.timers.size, 0);
});

test("event socket dispatches chat envelopes in arrival order", async () => {
  const env = environment();
  const seen = [];
  env.window.addEventListener("xalling:chat-event", (event) => seen.push(event.detail));
  const call = env.api.connectEvents();
  env.sockets[0].open();
  await call;
  env.sockets[0].receive({ type: "event", event: "chat", data: { event: "assistant.reply.delta" } });
  assert.equal(seen[0].event, "assistant.reply.delta");
  env.sockets[0].receive({ type: "event", event: "chat", data: { event: "turn.completed" } });
  assert.deepEqual(seen.map((event) => event.event), ["assistant.reply.delta", "turn.completed"]);
  env.window.dispatchEvent(new Event("beforeunload"));
});

test("disconnect signals recovery and reconnects the event channel", async () => {
  const env = environment();
  const ready = [];
  let disconnected = 0;
  env.window.addEventListener("xalling:transport-ready", (event) => ready.push(event.detail.reconnected));
  env.window.addEventListener("xalling:transport-disconnected", () => disconnected++);
  const connection = env.api.connectEvents();
  env.sockets[0].open();
  await connection;
  env.sockets[0].close();
  assert.equal(disconnected, 1);
  const [handle, reconnect] = [...env.timers].find(([, timer]) => timer.delay === 500);
  env.timers.delete(handle);
  reconnect.callback();
  env.sockets[1].open();
  await tick();
  assert.deepEqual(ready, [false, true]);
  assert.equal(env.sockets[1].sent.length, 0);
  assert.deepEqual(Array.from(env.sockets[1].protocols), ["xalling", "auth.test-credential"]);
  env.window.dispatchEvent(new Event("beforeunload"));
  assert.equal(env.timers.size, 0);
});

test("missing credentials fail immediately without creating a socket", async () => {
  const env = environment("");
  await assert.rejects(env.api.connectEvents(), /连接凭证/);
  assert.equal(env.sockets.length, 0);
});

test("recovery requests completed turns and buffers live events behind the snapshot", async () => {
  const window = new EventTarget();
  const calls = [];
  const seen = [];
  const recovered = [];
  let completeSnapshot;
  class CustomEvent extends Event {
    constructor(type, { detail }) {
      super(type);
      this.detail = detail;
    }
  }
  const exports = {};
  const client = ts.transpileModule(
    readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  runInNewContext(client, {
    exports, window,
    require: (module) => module === "./http"
      ? {
        request: (method, path, options) => {
          calls.push({ method, path, options });
          return new Promise((resolve) => { completeSnapshot = resolve; });
        },
      }
      : { TRANSPORT_READY_EVENT: "ready" },
  });
  const unsubscribe = exports.subscribeChatEvents("session-1", (event) => seen.push(event.id), (snapshot) => recovered.push(snapshot.running));
  const envelope = (id, event) => ({
    session_id: "session-1",
    render: { id, event, turn_id: "turn-1", session_id: "session-1", data: {}, created_at: "now", model_turn_id: null, parent_tool_use_id: null },
  });
  window.dispatchEvent(new CustomEvent("ready", { detail: { reconnected: false } }));
  assert.equal(calls.length, 0);
  window.dispatchEvent(new CustomEvent("ready", { detail: { reconnected: true } }));
  await tick();
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].path, "/api/chat/sessions/session-1/active");
  assert.equal(calls[0].options.query.include_completed, true);
  window.dispatchEvent(new CustomEvent("xalling:chat-event", { detail: envelope("live", "assistant.reply.delta") }));
  assert.equal(seen.length, 0);
  completeSnapshot({ session_id: "session-1", running: false, events: [envelope("snapshot", "turn.completed")] });
  await tick();
  assert.deepEqual(seen, ["snapshot", "live"]);
  assert.deepEqual(recovered, [false]);
  unsubscribe();
  window.dispatchEvent(new CustomEvent("ready", { detail: { reconnected: true } }));
  assert.equal(calls.length, 1);
});
