import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { typescriptLoader } from "./helpers/load-typescript.mjs";

test("knowledge tree and file queries remain read-only", async () => {
  const requests = [];
  const load = typescriptLoader({
    globals: { window: new EventTarget() },
    overrides: {
      "./http": { request: async (method, path, options) => { requests.push({ method, path, options }); return {}; } },
      "./websocket": {},
    },
  });
  const api = load(fileURLToPath(new URL("../src/api/client.ts", import.meta.url)));
  await api.getKnowledgeTree();
  await api.listKnowledgeDocuments("D:/资料/嵌入式", 20, "esp32");
  await api.listKnowledgeDocuments();
  assert.ok(requests.every(({ method }) => method === "GET"));
  assert.equal(requests[0].path, "/api/knowledge/tree");
  assert.equal(requests[1].options.query.parent_path, "D:/资料/嵌入式");
  assert.equal(requests[1].options.query.filename, "esp32");
  assert.equal(requests[1].options.query.offset, 20);
  assert.equal(requests[2].options.query.parent_path, undefined);
  for (const name of ["createKnowledgeCategory", "listKnowledgeCategories", "updateKnowledgeCategoryDescription", "importKnowledgeFile", "removeKnowledgeDocument", "getKnowledgeDocumentPreview", "readKnowledgeDocument"]) {
    assert.equal(api[name], undefined);
  }
});

test("document deletion submits exactly the confirmed source list", async () => {
  const requests = [];
  const load = typescriptLoader({
    globals: { window: new EventTarget() },
    overrides: {
      "./http": { request: async (method, path, options) => { requests.push({ method, path, options }); return { deleted: 2 }; } },
      "./websocket": {},
    },
  });
  const api = load(fileURLToPath(new URL("../src/api/client.ts", import.meta.url)));
  const sources = ["C:\\资料\\a.pdf", "C:\\资料\\nested\\b.pdf"];
  assert.equal((await api.deleteKnowledgeDocuments(sources)).deleted, 2);
  assert.equal(requests[0].method, "DELETE");
  assert.equal(requests[0].path, "/api/knowledge/documents");
  assert.deepEqual(requests[0].options.body.sources, sources);
});

test("embedding status is read-only and downloading requires an explicit POST", async () => {
  const requests = [];
  const load = typescriptLoader({
    globals: { window: new EventTarget() },
    overrides: {
      "./http": { request: async (method, path, options) => { requests.push({ method, path, options }); return {}; } },
      "./websocket": {},
    },
  });
  const api = load(fileURLToPath(new URL("../src/api/client.ts", import.meta.url)));
  await api.getKnowledgeEmbeddingStatus();
  await api.downloadKnowledgeEmbedding();
  assert.equal(requests[0].method, "GET");
  assert.equal(requests[0].path, "/api/knowledge/embedding");
  assert.equal(requests[1].method, "POST");
  assert.equal(requests[1].path, "/api/knowledge/embedding/download");
  assert.ok(requests[1].options.timeoutMs >= 30 * 60 * 1000);
});
