import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

import { typescriptLoader } from "./helpers/load-typescript.mjs";

function component(name, api, globals = {}) {
  const module = { exports: {} };
  const compiled = ts.transpileModule(
    readFileSync(new URL(`../src/components/${name}.tsx`, import.meta.url), "utf8"),
    { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    } },
  ).outputText;
  const overrides = {
    "react": { useRef: (current) => ({ current }) },
    "react/jsx-runtime": {
      jsx: (type, props) => ({ type, props }),
      jsxs: (type, props) => ({ type, props }),
      Fragment: "Fragment",
    },
    "antd": { Button: "Button" },
    "@ant-design/icons": {},
    "../api/client": api,
    "./TutorialHelp": { TutorialHelp: "TutorialHelp" },
  };
  runInNewContext(compiled, {
    module, exports: module.exports,
    require: (name) => {
      assert.ok(Object.hasOwn(overrides, name), `unexpected import ${name}`);
      return overrides[name];
    },
    ...globals,
  });
  return module.exports;
}

function elements(node) {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== "object") return [];
  return [node, ...elements(node.props?.children)];
}

test("window capabilities use the authenticated central HTTP client", async () => {
  const requests = [];
  const window = new EventTarget();
  const load = typescriptLoader({
    globals: { window },
    overrides: {
      "./http": { request: async (method, path) => {
        requests.push([method, path]);
        return { native_window: false };
      } },
      "./websocket": {},
    },
  });
  const api = load(fileURLToPath(new URL("../src/api/client.ts", import.meta.url)));
  assert.equal((await api.getWindowCapabilities()).native_window, false);
  assert.deepEqual(requests, [["GET", "/api/window/capabilities"]]);
});

test("headless title bar keeps help without any native window buttons", () => {
  const actions = [];
  const { TitleBar } = component("TitleBar", {
    minimizeWindow: () => actions.push("minimize"),
    toggleMaximizeWindow: () => actions.push("maximize"),
    closeWindow: () => actions.push("close"),
  });
  const nodes = elements(TitleBar({
    nativeWindowAvailable: false, maximized: false, onMaximizedChange: () => {},
  }));
  const buttons = nodes.filter((node) => node.type === "Button");
  assert.deepEqual(buttons, []);
  assert.ok(nodes.some((node) => node.type === "TutorialHelp"));
  const drag = nodes.find((node) => node.props?.className?.startsWith("title-bar-drag"));
  assert.equal(drag.props.onDoubleClick, undefined);
  assert.equal(drag.props.className.includes("pywebview-drag-region"), false);
  assert.deepEqual(actions, []);
});

test("desktop title bar retains native window actions", async () => {
  const actions = [];
  const { TitleBar } = component("TitleBar", {
    minimizeWindow: () => actions.push("minimize"),
    toggleMaximizeWindow: async () => { actions.push("maximize"); return true; },
    closeWindow: () => actions.push("close"),
  });
  const nodes = elements(TitleBar({
    nativeWindowAvailable: true, maximized: false,
    onMaximizedChange: (value) => actions.push(value),
  }));
  nodes.find((node) => node.props?.["aria-label"] === "最小化").props.onClick();
  nodes.find((node) => node.props?.["aria-label"] === "最大化窗口").props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  nodes.find((node) => node.props?.["aria-label"] === "关闭窗口").props.onClick();
  assert.deepEqual(actions, ["minimize", "maximize", true, "close"]);
});

test("disabled resize handles do not expose pointer targets or issue requests", () => {
  const requests = [];
  const { WindowResizeHandles } = component("WindowResizeHandles", {
    resizeWindow: (...args) => requests.push(args),
  });
  assert.equal(WindowResizeHandles({ disabled: true }), null);
  assert.deepEqual(requests, []);
});

test("enabled desktop resize handles still submit native resizing", async () => {
  const requests = [], frames = [];
  const { WindowResizeHandles } = component("WindowResizeHandles", {
    resizeWindow: async (...args) => { requests.push(args); },
  }, {
    window: { innerWidth: 1280, innerHeight: 820 },
    requestAnimationFrame: (callback) => { frames.push(callback); return frames.length; },
  });
  const target = elements(WindowResizeHandles({ disabled: false }))
    .find((node) => node.props?.className === "window-resize-handle window-resize-e");
  target.props.onPointerDown({
    button: 0, pointerId: 1, screenX: 100, screenY: 100,
    preventDefault() {}, currentTarget: { setPointerCapture() {} },
  });
  target.props.onPointerMove({ pointerId: 1, screenX: 120, screenY: 100 });
  frames.shift()();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, [[1300, 820, "e"]]);
});
