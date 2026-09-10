export type ClaudeCommandInvocation = {
  args: string;
  name: string;
};

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function commandArgsFromInput(value: string): string {
  return value.replace(/^\/[^\s/]+\s*/u, "").trim();
}

export function formatClaudeCommand(command: ClaudeCommandInvocation): string {
  const name = escapeXml(command.name);
  return `<command-name>/${name}</command-name>
<command-message>${name}</command-message>
<command-args>${escapeXml(command.args)}</command-args>`;
}

export function parseClaudeCommand(content: string): ClaudeCommandInvocation | null {
  if (!content.includes("<command-name>") || !content.includes("<command-args>")) {
    return null;
  }
  const documentNode = new DOMParser().parseFromString(
    `<root>${content}</root>`,
    "application/xml",
  );
  if (documentNode.querySelector("parsererror")) {
    return null;
  }
  const root = documentNode.documentElement;
  const hasUnexpectedText = Array.from(root.childNodes).some(
    (node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()),
  );
  const name = root.querySelector(":scope > command-name")?.textContent?.trim() ?? "";
  const message = root.querySelector(":scope > command-message")?.textContent;
  const args = root.querySelector(":scope > command-args")?.textContent?.trim();
  if (hasUnexpectedText || !name.startsWith("/") || message === undefined || args === undefined) {
    return null;
  }
  return { name: name.slice(1), args };
}

export function commandDisplayText(content: string): string {
  const command = parseClaudeCommand(content);
  return command ? `/${command.name}${command.args ? ` ${command.args}` : ""}` : content;
}
