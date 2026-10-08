import { fileURLToPath } from "node:url";
import { typescriptLoader } from "./load-typescript.mjs";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const file = (path) => fileURLToPath(new URL(path, import.meta.url));
const load = typescriptLoader({ overrides: { [file("../../src/api/client.ts")]: {
  isPermissionRequestEvent: (item) => item.kind === "permission.requested",
} } });
const { conversationFromEvents } = load(file("../../src/chat/conversation.ts"));
const rows = JSON.parse(input).map((events) => conversationFromEvents(events.map((item) => ({ ...item, kind: item.event }))));
process.stdout.write(JSON.stringify(rows));
