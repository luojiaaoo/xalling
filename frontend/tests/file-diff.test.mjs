import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { typescriptLoader } from "./helpers/load-typescript.mjs";

const load = typescriptLoader();
const { parseUnifiedDiff, splitDiffLines } = load(fileURLToPath(new URL("../src/chat/file-diff.ts", import.meta.url)));
const plain = (value) => JSON.parse(JSON.stringify(value));

test("diff line numbers follow separate hunks and paired edits", () => {
  const patch = "diff --git a/file b/file\r\n--- a/file\r\n+++ b/file\r\n@@ -2,3 +2,4 @@\r\n keep\r\n-old\r\n+new\r\n+extra\r\n end\r\n@@ -20 +21 @@\r\n-last\r\n+next\r\n";
  const lines = parseUnifiedDiff(patch).lines.filter((line) => line.kind !== "meta");
  assert.deepEqual(plain(lines), [
    { kind: "context", text: "keep", oldLine: 2, newLine: 2 },
    { kind: "remove", text: "old", oldLine: 3 },
    { kind: "add", text: "new", newLine: 3 },
    { kind: "add", text: "extra", newLine: 4 },
    { kind: "context", text: "end", oldLine: 4, newLine: 5 },
    { kind: "remove", text: "last", oldLine: 20 },
    { kind: "add", text: "next", newLine: 21 },
  ]);
  const paired = splitDiffLines(lines);
  assert.equal(paired[1].left.text, "old");
  assert.equal(paired[1].right.text, "new");
  assert.equal(paired[2].left, undefined);
  assert.equal(paired[2].right.text, "extra");
});

test("new and deleted files, combined hunks and rendering limits", () => {
  const added = parseUnifiedDiff("--- /dev/null\n+++ b/new\n@@ -0,0 +1,2 @@\n+a\n+\n").lines.at(-1);
  assert.equal(added.newLine, 2);
  assert.equal(added.oldLine, undefined);
  const deleted = parseUnifiedDiff("@@ -1,2 +0,0 @@\n-a\n-b\n").lines.at(-1);
  assert.equal(deleted.oldLine, 2);
  assert.equal(deleted.newLine, undefined);
  assert.ok(parseUnifiedDiff("@@@ -1,1 -1,1 +1,1 @@@\n++a\n").lines.every((line) => line.oldLine === undefined));
  const limited = parseUnifiedDiff("one\ntwo\nthree\n", 2);
  assert.equal(limited.lines.length, 2);
  assert.equal(limited.truncated, true);
});

test("split deletion keeps the after side empty and aligns the following context", () => {
  const lines = parseUnifiedDiff("--- file\n+++ file\n@@ -1,4 +1,1 @@\n title\n-first\n-second\n-third\n").lines;
  const rows = splitDiffLines(lines).filter((row) => row.meta === undefined);
  assert.equal(rows[0].left.text, "title");
  assert.equal(rows[0].right.text, "title");
  assert.deepEqual(plain(rows.slice(1).map((row) => row.left.oldLine)), [2, 3, 4]);
  assert.ok(rows.slice(1).every((row) => row.right === undefined));
});
