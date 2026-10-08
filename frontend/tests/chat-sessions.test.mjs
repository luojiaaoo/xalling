import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { typescriptLoader } from "./helpers/load-typescript.mjs";

const load = typescriptLoader();
const { groupChatSessions } = load(fileURLToPath(new URL("../src/chat/sessions.ts", import.meta.url)));
const session = (session_id, cwd, created_at, last_modified = 0) => ({
  session_id, cwd, created_at, last_modified,
});
const order = (sessions, pinned = null) => Array.from(groupChatSessions(sessions, pinned), (group) => (
  [group.key, Array.from(group.sessions, (item) => item.session_id)]
));

test("opening or continuing an older session cannot move its row or project to the top", () => {
  const sessions = [
    session("older", "C:/older", 100, 900),
    session("newest", "C:/newer", 300, 400),
    session("recent", "C:/newer", 200, 500),
  ];
  const expected = [["C:/newer", ["newest", "recent"]], ["C:/older", ["older"]]];
  assert.deepEqual(order(sessions), expected);
  const refreshed = sessions.map((item) => ({
    ...item, last_modified: item.session_id === "newest" ? 400 : 10_000, running: true,
  })).reverse();
  assert.deepEqual(order(refreshed), expected);
  assert.deepEqual(sessions.map((item) => item.session_id), ["older", "newest", "recent"]);
});

test("missing creation times and equal times keep deterministic order across refreshes", () => {
  const sessions = [
    session("unknown-b", "C:/same", null, 10_000),
    session("known-b", "C:/same", 100, 9_000),
    session("unknown-a", "C:/same", null),
    session("known-a", "C:/same", 100),
    session("other", "C:/other", 100),
    session("no-project", null, null),
  ];
  const expected = [
    ["C:/other", ["other"]],
    ["C:/same", ["known-a", "known-b", "unknown-a", "unknown-b"]],
    ["__unknown_project__", ["no-project"]],
  ];
  assert.deepEqual(order(sessions), expected);
  assert.deepEqual(order([...sessions].reverse()), expected);
});

test("the default project stays pinned while new sessions follow creation order", () => {
  const sessions = [session("old", "C:/default", 100), session("recent", "C:/other", 200)];
  assert.deepEqual(order(sessions, "C:/default"), [
    ["C:/default", ["old"]], ["C:/other", ["recent"]],
  ]);
  assert.deepEqual(order([...sessions, session("new", "C:/other", 300)]), [
    ["C:/other", ["new", "recent"]], ["C:/default", ["old"]],
  ]);
  assert.deepEqual(order([], "C:/default"), []);
});
