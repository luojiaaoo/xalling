import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import ts from "typescript";

import { typescriptLoader } from "./helpers/load-typescript.mjs";

const tree = typescriptLoader()(fileURLToPath(new URL("../src/knowledge/tree.ts", import.meta.url)));
const compiled = ts.transpileModule(readFileSync(new URL("../src/components/Knowledge.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const tick = () => new Promise((resolve) => setImmediate(resolve));
const plain = (value) => JSON.parse(JSON.stringify(value));

function walk(node) {
  if (Array.isArray(node)) return node.flatMap(walk);
  if (!node || typeof node !== "object") return [];
  return [node, ...walk(node.props?.children)];
}

async function panel(remove = async () => ({ deleted: 2 }), embedding = { status: "ready", message: "ready" }, syncState = { status: "idle", completed_files: 0, total_files: 0, message: "" }, sync = async () => ({ ...syncState, status: "completed" }), download = async () => embedding) {
  const sources = ["C:/Users/user/docs/a.pdf", "C:/Users/user/docs/nested/b.pdf", "C:/Users/user/other/c.pdf"];
  let files = [...sources], cursor = 0, initialized = false, view;
  const slots = [], effects = [], cleanups = [], requests = [], successes = [];
  const jsx = (type, props) => typeof type === "function" ? type(props) : { type, props };
  const exports = {};
  runInNewContext(compiled, {
    exports, Error, Set, setTimeout, clearTimeout,
    require: (name) => {
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
      if (name === "react") return {
        useState: (initial) => {
          const index = cursor++;
          if (!(index in slots)) slots[index] = initial;
          return [slots[index], (next) => { slots[index] = typeof next === "function" ? next(slots[index]) : next; }];
        },
        useRef: (initial) => {
          const index = cursor++;
          return slots[index] ??= { current: initial };
        },
        useCallback: (fn) => fn,
        useMemo: (fn) => fn(),
        useEffect: (fn) => { if (!initialized) effects.push(fn); },
      };
      if (name === "antd") return {
        Alert: "Alert", Button: "Button", Empty: "Empty", Modal: "Modal", Progress: "Progress", Spin: "Spin", Tooltip: "Tooltip", Tree: { DirectoryTree: "Tree" },
        App: { useApp: () => ({ message: { success: (text) => successes.push(text) } }) },
      };
      if (name === "@ant-design/icons") return {};
      if (name === "../knowledge/tree") return tree;
      if (name === "../api/client") return {
        getKnowledgeSyncStatus: async () => syncState,
        syncKnowledgeDocuments: sync,
        getKnowledgeEmbeddingStatus: async () => embedding,
        downloadKnowledgeEmbedding: download,
        getKnowledgeTree: async () => ({ directories: [{ path: "C:/Users/user", files: [...files] }] }),
        deleteKnowledgeDocuments: async (selected) => {
          requests.push(plain(selected));
          const result = await remove(selected);
          files = files.filter((path) => !selected.includes(path));
          return result;
        },
      };
      throw new Error(`Unexpected dependency: ${name}`);
    },
  });
  const render = () => { cursor = 0; view = exports.Knowledge({ open: true, onClose: () => {} }); return view; };
  render();
  initialized = true;
  effects.forEach((effect) => cleanups.push(effect()));
  await tick();
  render();
  const allTreeNodes = () => {
    const flatten = (nodes) => nodes.flatMap((node) => [node, ...flatten(node.children ?? [])]);
    return walk(view).filter((node) => node.type === "Tree").flatMap((node) => flatten(node.props.treeData));
  };
  return {
    requests, successes, sources, render, allTreeNodes,
    button: (path) => walk(allTreeNodes().find((node) => node.title.props.children[0].props.title === path).title)
      .find((node) => node.type === "Button"),
    confirmation: () => walk(view).find((node) => node.type === "Modal" && node.props.okText === "删除文档"),
    syncConfirmation: () => walk(view).find((node) => node.type === "Modal" && node.props.title === "同步知识库？"),
    progressNodes: () => walk(walk(view).find((node) => node.type === "Alert")?.props.description),
    downloadButton: () => walk(walk(view).find((node) => node.type === "Alert")?.props.action).find((node) => node.type === "Button"),
    syncButton: () => walk(view).find((node) => node.type === "Button" && node.props.children === "同步知识库"),
    refreshButton: () => walk(view).find((node) => node.props?.["aria-label"] === "刷新知识库列表"),
    syncProgress: () => walk(view).find((node) => node.props?.["aria-label"] === "知识库同步进度"),
    refreshEmbedding: async (next) => {
      embedding = next;
      await walk(view).find((node) => node.props?.["aria-label"] === "刷新知识库列表").props.onClick();
      await tick();
      render();
    },
    dispose: () => cleanups.forEach((cleanup) => cleanup?.()),
  };
}

test("reopening the panel restores sync progress and disables deletion", async () => {
  const env = await panel(undefined, undefined, { status: "running", completed_files: 2, total_files: 4, message: "同步中" });
  assert.equal(env.syncProgress().props.percent, 50);
  assert.equal(env.syncProgress().props.status, "active");
  assert.equal(env.syncButton().props.loading, true);
  assert.equal(env.button(env.sources[0]).props.disabled, true);
  env.dispose();
});

test("sync requires confirmation, prevents duplicate submissions and shows completion", async () => {
  let finish, calls = 0;
  const env = await panel(undefined, undefined, undefined, () => {
    calls += 1;
    return new Promise((resolve) => { finish = resolve; });
  });
  assert.equal(calls, 0);
  env.syncButton().props.onClick();
  env.syncButton().props.onClick();
  env.render();
  assert.equal(calls, 0);
  assert.equal(env.syncConfirmation().props.open, true);
  env.syncConfirmation().props.onOk();
  env.syncConfirmation().props.onOk();
  env.render();
  assert.equal(calls, 1);
  assert.equal(env.syncConfirmation().props.open, false);
  assert.equal(env.button(env.sources[0]).props.disabled, true);
  finish({ status: "completed", completed_files: 3, total_files: 3, message: "同步完成" });
  await tick();
  env.render();
  assert.equal(env.syncProgress().props.percent, 100);
  assert.equal(env.syncButton().props.loading, false);
  env.dispose();
});

test("cancelling sync and refreshing the list never start synchronization", async () => {
  let calls = 0;
  const env = await panel(undefined, undefined, undefined, async () => { calls += 1; });
  try {
    env.syncButton().props.onClick();
    env.render();
    assert.equal(env.syncConfirmation().props.open, true);
    const details = walk(env.syncConfirmation()).filter((node) => node.type === "li").map((node) => node.props.children);
    assert.ok(details.includes("更新已修改文件的内容与检索索引。"));
    assert.ok(details.includes("移除原文件已删除的知识库记录。"));
    env.syncConfirmation().props.onCancel();
    env.render();
    assert.equal(env.syncConfirmation().props.open, false);
    assert.equal(env.refreshButton().props.children, "刷新列表");
    env.refreshButton().props.onClick();
    await tick();
    env.render();
    assert.equal(calls, 0);
    assert.equal(env.syncConfirmation().props.open, false);
  } finally {
    env.dispose();
  }
});

test("embedding progress shows bytes, unknown totals and validation without claiming readiness", async () => {
  const downloading = {
    status: "downloading", message: "下载中",
    progress: { phase: "downloading", downloaded_bytes: 1024 ** 2, total_bytes: 4 * 1024 ** 2, completed_files: 1, total_files: 5 },
  };
  const env = await panel(undefined, downloading);
  let progress = env.progressNodes().find((node) => node.type === "Progress");
  assert.equal(progress.props.percent, 25);
  assert.equal(progress.props.format(), "25%");
  let label = env.progressNodes().find((node) => node.type === "p").props.children.flat(Infinity).join("");
  assert.match(label, /1\.0 MiB \/ 4\.0 MiB/);
  assert.match(label, /文件 1\/5/);

  await env.refreshEmbedding({ ...downloading, progress: { ...downloading.progress, total_bytes: null } });
  progress = env.progressNodes().find((node) => node.type === "Progress");
  assert.equal(progress.props.format(), "下载中");
  assert.equal(progress.props.percent, 0);

  await env.refreshEmbedding({ ...downloading, progress: { ...downloading.progress, downloaded_bytes: 4 * 1024 ** 2 } });
  assert.equal(env.progressNodes().find((node) => node.type === "Progress").props.percent, 99);
  await env.refreshEmbedding({ ...downloading, progress: { ...downloading.progress, phase: "validating", downloaded_bytes: 4 * 1024 ** 2 } });
  progress = env.progressNodes().find((node) => node.type === "Progress");
  assert.equal(progress.props.percent, 100);
  assert.equal(progress.props.format(), "验证中");
  assert.equal(progress.props.status, "active");

  await env.refreshEmbedding({ status: "ready", message: "ready", progress: null });
  assert.equal(env.progressNodes().filter((node) => node.type === "Progress").length, 0);
  env.dispose();
});

test("clicking download immediately shows progress while the download request is pending", async () => {
  let finish, calls = 0;
  const env = await panel(undefined, { status: "missing", message: "模型未下载", progress: null }, undefined, undefined, () => {
    calls += 1;
    return new Promise((resolve) => { finish = resolve; });
  });
  try {
    assert.equal(calls, 0);
    assert.equal(env.progressNodes().filter((node) => node.type === "Progress").length, 0);
    env.downloadButton().props.onClick();
    env.render();
    const progress = env.progressNodes().find((node) => node.type === "Progress");
    assert.equal(calls, 1);
    assert.equal(progress.props["aria-label"], "嵌入模型下载进度");
    assert.equal(progress.props.status, "active");
    assert.equal(progress.props.format(), "准备中");
    assert.equal(env.downloadButton().props.loading, true);
    env.downloadButton().props.onClick();
    assert.equal(calls, 1);

    await env.refreshEmbedding({ status: "ready", message: "模型已就绪", progress: null });
    finish();
    await tick();
    env.render();
    assert.equal(env.progressNodes().filter((node) => node.type === "Progress").length, 0);
    assert.equal(env.downloadButton(), undefined);
  } finally {
    finish?.();
    env.dispose();
  }
});

test("only non-root nodes have delete buttons and opening or cancelling confirmation never deletes", async () => {
  const env = await panel();
  const root = env.allTreeNodes()[0];
  assert.equal(walk(root.title).filter((node) => node.type === "Button").length, 0);
  assert.ok(env.allTreeNodes().slice(1).every((node) => walk(node.title).some((child) => child.type === "Button")));
  let stopped = false;
  env.button(env.sources[0]).props.onClick({ stopPropagation: () => { stopped = true; } });
  env.render();
  assert.equal(stopped, true);
  assert.equal(env.confirmation().props.open, true);
  const listed = walk(env.confirmation()).filter((node) => node.type === "li").map((node) => node.props.children);
  assert.deepEqual(listed, [env.sources[0]]);
  assert.equal(env.requests.length, 0);
  env.confirmation().props.onCancel();
  env.render();
  assert.equal(env.confirmation().props.open, false);
  assert.equal(env.requests.length, 0);
  env.dispose();
});

test("folder deletion confirms all descendants, prevents duplicate requests and updates the tree", async () => {
  let finish;
  const env = await panel(() => new Promise((resolve) => { finish = resolve; }));
  env.button("C:\\Users\\user\\docs").props.onClick({ stopPropagation() {} });
  env.render();
  const confirmation = env.confirmation();
  const listed = walk(confirmation).filter((node) => node.type === "li").map((node) => node.props.children);
  assert.deepEqual([...listed].sort(), env.sources.slice(0, 2).sort());
  confirmation.props.onOk();
  confirmation.props.onOk();
  env.render();
  assert.deepEqual(env.requests, [listed]);
  assert.equal(env.confirmation().props.confirmLoading, true);
  env.confirmation().props.onCancel();
  env.render();
  assert.equal(env.confirmation().props.open, true);
  finish({ deleted: 2 });
  await tick();
  env.render();
  assert.equal(env.confirmation().props.open, false);
  assert.deepEqual(env.allTreeNodes().filter((node) => node.isLeaf).map((node) => node.title.props.children[0].props.title), [env.sources[2]]);
  assert.equal(env.successes.length, 1);
  env.dispose();
});

test("failed deletion keeps the confirmation and documents available for retry", async () => {
  const env = await panel(async () => { throw new Error("index unavailable"); });
  env.button(env.sources[0]).props.onClick({ stopPropagation() {} });
  env.render();
  env.confirmation().props.onOk();
  await tick();
  env.render();
  assert.equal(env.confirmation().props.open, true);
  assert.equal(env.confirmation().props.confirmLoading, false);
  assert.equal(walk(env.confirmation()).find((node) => node.type === "Alert").props.title, "index unavailable");
  assert.equal(env.allTreeNodes().filter((node) => node.isLeaf).length, 3);
  assert.equal(env.successes.length, 0);
  env.dispose();
});
