export type DiffLine = {
  kind: "meta" | "context" | "add" | "remove";
  text: string;
  oldLine?: number;
  newLine?: number;
};

export function parseUnifiedDiff(patch: string, limit = 5000): { lines: DiffLine[]; truncated: boolean } {
  const source = patch.replace(/\r\n/g, "\n").split("\n");
  if (source.at(-1) === "") source.pop();
  let oldLine: number | undefined;
  let newLine: number | undefined;
  const lines: DiffLine[] = [];
  for (const text of source.slice(0, limit)) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      lines.push({ kind: "meta", text });
    } else if (text.startsWith("diff ") || text.startsWith("@@@")) {
      oldLine = undefined;
      newLine = undefined;
      lines.push({ kind: "meta", text });
    } else if (oldLine !== undefined && newLine !== undefined && /^[ +\-]/.test(text)) {
      const kind = text[0] === "+" ? "add" : text[0] === "-" ? "remove" : "context";
      lines.push({ kind, text: text.slice(1),
        oldLine: kind === "add" ? undefined : oldLine,
        newLine: kind === "remove" ? undefined : newLine });
      if (kind !== "remove") newLine += 1;
      if (kind !== "add") oldLine += 1;
    } else lines.push({ kind: "meta", text });
  }
  return { lines, truncated: source.length > limit };
}

export type SplitDiffLine = { meta?: string; left?: DiffLine; right?: DiffLine };

export function splitDiffLines(lines: DiffLine[]): SplitDiffLine[] {
  const result: SplitDiffLine[] = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (line.kind === "meta") { result.push({ meta: line.text }); index += 1; continue; }
    if (line.kind === "context") { result.push({ left: line, right: line }); index += 1; continue; }
    const removed: DiffLine[] = [];
    const added: DiffLine[] = [];
    while (index < lines.length && (lines[index].kind === "remove" || lines[index].kind === "add")) {
      const changed = lines[index++];
      (changed.kind === "remove" ? removed : added).push(changed);
    }
    for (let row = 0; row < Math.max(removed.length, added.length); row += 1) {
      result.push({ left: removed[row], right: added[row] });
    }
  }
  return result;
}
