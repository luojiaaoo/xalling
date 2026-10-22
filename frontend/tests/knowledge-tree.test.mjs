import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { typescriptLoader } from "./helpers/load-typescript.mjs";

const load = typescriptLoader();
const { buildKnowledgeTree } = load(fileURLToPath(new URL("../src/knowledge/tree.ts", import.meta.url)));
const plain = (value) => JSON.parse(JSON.stringify(value));
const directory = (path, ...files) => ({ path, files });

test("Windows merges shared ancestors and creates one root per indexed drive", () => {
  const roots = buildKnowledgeTree({ directories: [
    directory("D:/资料", "D:/资料/手册.pdf"),
    directory("C:\\Users\\user\\Desktop", "C:\\Users\\user\\Desktop\\slides.pptx"),
    directory("C:\\Users\\user", "C:\\Users\\user\\guide.pdf"),
    directory("c:/Users/user/Downloads", "c:/Users/user/Downloads/paper.pdf"),
    directory("C:/Users/user", "C:/Users/user/guide.pdf"),
  ] });
  assert.deepEqual(plain(roots.map((node) => node.name)), ["C:\\", "D:\\"]);
  const user = roots[0].children[0];
  assert.equal(user.name, "Users\\user");
  assert.deepEqual(plain(user.children.map((node) => node.name)), ["Desktop", "Downloads", "guide.pdf"]);
  assert.equal(user.children[0].children[0].path, "C:\\Users\\user\\Desktop\\slides.pptx");
  assert.equal(roots[1].children[0].children[0].name, "手册.pdf");
});

test("Linux uses a single slash root and preserves case and backslashes in names", () => {
  const roots = buildKnowledgeTree({ directories: [
    directory("/home/user/docs", "/home/user/docs/paper.pdf", "/home/user/docs/Paper.pdf", "/home/user/docs/a\\b.txt"),
    directory("/home/user", "/home/user/readme.md"),
    directory("/opt/manuals", "/opt/manuals/guide.pdf"),
  ] });
  assert.equal(roots.length, 1);
  assert.equal(roots[0].name, "/");
  assert.deepEqual(plain(roots[0].children.map((node) => node.name)), ["home/user", "opt/manuals"]);
  const user = roots[0].children[0];
  assert.deepEqual(plain(user.children.map((node) => node.name)), ["docs", "readme.md"]);
  assert.equal(user.children[0].children.length, 3);
  assert.ok(user.children[0].children.some((node) => node.name === "a\\b.txt"));
});

test("drive-root files, UNC shares and empty results remain valid trees", () => {
  assert.equal(buildKnowledgeTree({ directories: [] }).length, 0);
  const roots = buildKnowledgeTree({ directories: [
    directory("C:\\", "C:\\root.pdf"),
    directory("\\\\server\\share\\docs", "\\\\server\\share\\docs\\network.pdf"),
  ] });
  const drive = roots.find((node) => node.name === "C:\\");
  assert.equal(drive.children[0].name, "root.pdf");
  assert.equal(drive.children[0].isLeaf, true);
  const share = roots.find((node) => node.name === "\\\\server\\share\\");
  assert.equal(share.children[0].name, "docs");
  assert.equal(share.children[0].children[0].name, "network.pdf");
});

test("compact folder chains stop at branches and never absorb roots or files", () => {
  const roots = buildKnowledgeTree({ directories: [
    directory("C:/Users/user/docs/deep", "C:/Users/user/docs/deep/report.pdf"),
    directory("C:/Users/user/images", "C:/Users/user/images/photo.png"),
    directory("/home/user/docs", "/home/user/docs/readme.md"),
  ] });
  const drive = roots.find((node) => node.name === "C:\\");
  const user = drive.children[0];
  assert.equal(user.name, "Users\\user");
  assert.deepEqual(plain(user.children.map((node) => node.name)), ["docs\\deep", "images"]);
  const docs = user.children[0];
  assert.equal(docs.path, "C:\\Users\\user\\docs\\deep");
  assert.equal(docs.key, "directory:c:/users/user/docs/deep");
  assert.equal(docs.children[0].name, "report.pdf");
  assert.equal(docs.children[0].isLeaf, true);
  const linux = roots.find((node) => node.name === "/");
  assert.equal(linux.children[0].name, "home/user/docs");
  assert.equal(linux.children[0].path, "/home/user/docs");
  assert.equal(linux.children[0].children[0].name, "readme.md");
});
