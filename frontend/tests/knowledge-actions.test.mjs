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

async function panel(remove = async () => ({ deleted: 2 })) {
  const sources = ["C:/Users/user/docs/a.pdf", "C:/Users/user/docs/nested/b.pdf", "C:/Users/user/other/c.pdf"];
  let files = [...sources], cursor = 0, initialized = false, view;
  const slots = [], effects = [], cleanups = [], requests = [], successes = [];
  const jsx = (type, props) => typeof type === "function" ? type(props) : { type, props };
  const exports = {};
  runInNewContext(compiled, {
    exports, Error, Set,
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
        Alert: "Alert", Button: "Button", Empty: "Empty", Modal: "Modal", Spin: "Spin", Tree: { DirectoryTree: "Tree" },
        App: { useApp: () => ({ message: { success: (text) => successes.push(text) } }) },
      };
      if (name === "@ant-design/icons") return {};
      if (name === "../knowledge/tree") return tree;
      if (name === "../api/client") return {
        getKnowledgeEmbeddingStatus: async () => ({ status: "ready", message: "ready" }),
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
    confirmation: () => walk(view).find((node) => node.type === "Modal" && node.props.title !== "本地知识库"),
    dispose: () => cleanups.forEach((cleanup) => cleanup?.()),
  };
}

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
