import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { typescriptLoader } from "./helpers/load-typescript.mjs";

const file = (path) => fileURLToPath(new URL(path, import.meta.url));
const api = { isPermissionRequestEvent: (item) => item.kind === "permission.requested"
  && typeof item.data.request_id === "string" && typeof item.data.tool_name === "string" };
const load = typescriptLoader({ overrides: { [file("../src/api/client.ts")]: api } });
const { conversationFromEvents, reduceConversationEvent, pendingPermissionsFromEvents } = load(file("../src/chat/conversation.ts"));
const { applyRenderEvent } = load(file("../src/chat/trace.ts"));
let sequence = 0;
const event = (kind, data = {}, options = {}) => ({ id: `event-${++sequence}`, kind, event: kind,
  turn_id: "turn", model_turn_id: "model", session_id: "session", parent_tool_use_id: null,
  created_at: "2026-10-08T00:00:00Z", data, ...options });
const plain = (value) => JSON.parse(JSON.stringify(value));
const assistant = (messages) => messages.find((item) => item.key === "turn-turn-assistant");

test("checkpoints attach to user messages and restoring earlier files creates no assistant turn", () => {
  const messages = conversationFromEvents([
    event("turn.started"), event("user.message", { content: "edit files" }),
    event("files.checkpoint", { checkpoint_id: "checkpoint" }),
    event("turn.completed", { content: "done" }),
    event("turn.started", {}, { turn_id: "next" }),
    event("user.message", { content: "continue" }, { turn_id: "next" }),
    event("turn.completed", { content: "next done" }, { turn_id: "next" }),
  ]);
  const restored = reduceConversationEvent(messages, event("files.restored", { checkpoint_id: "checkpoint" }));
  assert.equal(restored.length, messages.length);
  assert.equal(restored[0].checkpointId, "checkpoint");
  assert.equal(restored[0].filesRestoredAt, "2026-10-08T00:00:00Z");
  assert.equal(restored.filter((item) => item.loading).length, 0);
  assert.equal(restored.find((item) => item.key === "turn-next-assistant").content, "next done");
});

test("file changes stay attached to their completed turn and empty net snapshots clear earlier changes", () => {
  const files = [{ path: "file", additions: 2, deletions: 1, patch: "patch", partial: false, restorable: true }];
  let messages = conversationFromEvents([
    event("turn.started"), event("user.message", { content: "edit" }),
    event("files.checkpoint", { checkpoint_id: "checkpoint" }),
    event("files.changed", { files }),
    event("turn.completed", { content: "done" }),
    event("turn.started", {}, { turn_id: "next" }),
    event("user.message", { content: "continue" }, { turn_id: "next" }),
    event("files.changed", { files: [{ ...files[0], additions: 5 }] }, { turn_id: "next" }),
    event("turn.completed", { content: "next done" }, { turn_id: "next" }),
  ]);
  assert.equal(assistant(messages).fileChanges[0].additions, 2);
  assert.equal(assistant(messages).checkpointId, "checkpoint");
  assert.equal(messages.find((item) => item.key === "turn-next-assistant").fileChanges[0].additions, 5);
  messages = reduceConversationEvent(messages, event("files.restored", { checkpoint_id: "checkpoint" }));
  assert.equal(assistant(messages).filesRestoredAt, "2026-10-08T00:00:00Z");
  messages = reduceConversationEvent(messages, event("files.changed", { files: [] }));
  assert.equal(assistant(messages).fileChanges.length, 0);
  assert.equal(assistant(messages).loading, false);
  assert.equal(assistant(messages).content, "done");
  assert.equal(messages.length, 4);
});

test("live and history share completion, absolute blocks and durations", () => {
  const begin = [event("turn.started"), event("user.message", { content: "hello" })];
  const complete = event("assistant.reply.completed", { trace_id: "model:1", text: "answer" });
  const terminal = event("turn.completed", { content: "answer", usage: { output_tokens: 2 } },
    { created_at: "2026-10-08T00:00:05Z" });
  const live = conversationFromEvents([...begin,
    event("assistant.reply.started", { trace_id: "model:1" }),
    event("assistant.reply.delta", { trace_id: "model:1", text: "ans" }),
    complete, complete, terminal, event("assistant.reply.delta", { trace_id: "model:1", text: "stale" })]);
  const replay = conversationFromEvents([...begin, complete, terminal]);
  assert.equal(live[0].role, "user");
  assert.equal(assistant(live).content, "answer");
  assert.equal(assistant(live).trace.length, 1);
  assert.equal(assistant(live).trace[0].content, "answer");
  assert.equal(assistant(live).loading, false);
  assert.equal(assistant(live).workingSeconds, 5);
  assert.deepEqual(plain(live), plain(replay));
  const late = reduceConversationEvent(live, event("assistant.reply.completed",
    { trace_id: "older:0", text: "older commentary" }, { model_turn_id: "older" }));
  assert.equal(assistant(late).content, "answer");
  assert.equal(assistant(late).loading, false);
});

test("equal text in different blocks remains present and previous model commentary stays in the trace", () => {
  const messages = conversationFromEvents([
    event("turn.started"), event("user.message", { content: "inspect" }),
    event("assistant.reply.completed", { trace_id: "model:0", text: "checking" }),
    event("tool.requested", { tool_id: "read", name: "Read" }),
    event("tool.completed", { tool_id: "read", output: "source" }),
    event("assistant.reply.completed", { trace_id: "next:0", text: "same" }, { model_turn_id: "next" }),
    event("assistant.reply.completed", { trace_id: "next:1", text: "same" }, { model_turn_id: "next" }),
    event("turn.completed", { content: "same\n\nsame" }),
  ]);
  const reply = assistant(messages);
  assert.equal(reply.content, "same\n\nsame");
  assert.equal(reply.trace[0].content, "checking");
  assert.equal(reply.finalOutputKeys.length, 2);
  assert.equal(reply.trace[1].calls[0].output, "source");
});

test("children arriving before parent tools are buffered and nested exactly once", () => {
  const parent = event("subagent.started", { tool_id: "agent", name: "Agent" });
  const messages = conversationFromEvents([
    event("turn.started"),
    event("subagent.reply.completed", { trace_id: "child:0", text: "found" }, { parent_tool_use_id: "nested" }),
    event("subagent.started", { tool_id: "nested", name: "Agent" }, { parent_tool_use_id: "agent" }),
    parent, parent,
    event("turn.completed", { content: "done" }),
  ]);
  const reply = assistant(messages);
  assert.equal(reply.trace[0].calls[0].trace[0].calls[0].trace[0].content, "found");
  assert.equal(reply.pendingTraceEvents, undefined);
  assert.equal(reply.trace[0].calls[0].status, "success");
});

for (const firstStatus of ["completed", "failed"]) test(`background siblings wait and preserve ${firstStatus} status`, () => {
  let trace = [];
  const apply = (kind, data) => { trace = applyRenderEvent(trace, event(kind, data)); };
  apply("subagent.started", { tool_id: "agent", name: "Agent" });
  apply("task.started", { task_id: "first", tool_use_id: "agent" });
  apply("task.started", { task_id: "second", tool_use_id: "agent" });
  apply("subagent.completed", { tool_id: "agent", output: "started in background" });
  apply("task.completed", { task_id: "first", status: firstStatus });
  assert.equal(trace[0].calls[0].status, "running");
  apply("task.completed", { task_id: "second", status: "completed" });
  assert.equal(trace[0].calls[0].status, firstStatus === "failed" ? "error" : "success");
  assert.equal(trace[0].calls[0].output, "started in background");
});

test("proxy results keep the human turn alive and task notifications never become user bubbles", () => {
  let messages = conversationFromEvents([
    event("turn.started"), event("user.message", { content: "work" }),
    event("assistant.reply.completed", { trace_id: "model:0", text: "waiting" }),
    event("turn.proxy.completed"), event("user.proxy.message", { content: "task-notification" }),
  ]);
  assert.equal(assistant(messages).loading, true);
  assert.equal(assistant(messages).content, "");
  messages = reduceConversationEvent(messages, event("assistant.reply.completed", { trace_id: "next:0", text: "done" }, { model_turn_id: "next" }));
  messages = reduceConversationEvent(messages, event("turn.completed", { content: "done" }));
  assert.equal(messages.filter((item) => item.role === "user").length, 1);
  assert.equal(assistant(messages).content, "done");
  assert.equal(assistant(messages).trace[0].content, "waiting");
});

test("resolved or closed-turn permissions stay closed and diagnostics create no replies", () => {
  const request = (id) => event("permission.requested", { request_id: id, tool_name: "Read" });
  const events = [request("old"), event("permission.resolved", { request_id: "old" }),
    request("pending"), event("turn.completed"), request("late")];
  assert.equal(pendingPermissionsFromEvents(events).length, 0);
  const messages = [];
  assert.equal(reduceConversationEvent(messages, event("sdk.unhandled")), messages);
  assert.equal(reduceConversationEvent(messages, event("assistant.message.completed")), messages);
});

test("stop and failure settle tools and removing plan content also applies to terminal history", () => {
  const start = [event("turn.started"), event("user.message", { content: "plan" }),
    event("plan.approval.requested", { tool_id: "plan", name: "ExitPlanMode", plan: "the plan" }),
    event("assistant.reply.completed", { trace_id: "model:0", text: "the plan\n\napproved" })];
  const completed = assistant(conversationFromEvents([...start, event("turn.completed", { content: "the plan\n\napproved" })]));
  assert.equal(completed.content, "approved");
  const stopped = assistant(conversationFromEvents([...start, event("turn.completed", { usage: { stop_reason: "interrupted" } })]));
  assert.equal(stopped.status, "abort");
  assert.equal(stopped.trace[0].calls[0].status, "success");
  const failed = assistant(conversationFromEvents([...start, event("turn.failed", { message: "broken" })]));
  assert.equal(failed.status, "error");
  assert.equal(failed.trace[0].calls[0].status, "error");
});
