import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { runInNewContext } from "node:vm";
import ts from "typescript";

export function typescriptLoader({ globals = {}, overrides = {} } = {}) {
  const cache = new Map();
  function load(file) {
    const path = resolve(file);
    if (Object.hasOwn(overrides, path)) return overrides[path];
    if (cache.has(path)) return cache.get(path).exports;
    const module = { exports: {} };
    cache.set(path, module);
    const compiled = ts.transpileModule(readFileSync(path, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const require = (name) => {
      if (Object.hasOwn(overrides, name)) return overrides[name];
      const dependency = resolve(dirname(path), name.replace(/\.js$/, ""));
      return load(dependency.endsWith(".ts") ? dependency : `${dependency}.ts`);
    };
    runInNewContext(compiled, { exports: module.exports, module, require, Date, Map, Set, Error, console, ...globals }, { filename: path });
    return module.exports;
  }
  return load;
}
