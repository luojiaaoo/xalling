import type { KnowledgeTree } from "../api/client";

export type KnowledgePathNode = {
  key: string;
  name: string;
  path: string;
  isLeaf: boolean;
  children?: KnowledgePathNode[];
};

export function collectKnowledgeSources(node: KnowledgePathNode): string[] {
  return node.isLeaf ? [node.path] : (node.children ?? []).flatMap(collectKnowledgeSources);
}

/** Build from source paths, independent of the browser's operating system. */
export function buildKnowledgeTree(data: KnowledgeTree): KnowledgePathNode[] {
  const roots: KnowledgePathNode[] = [];
  const nodes = new Map<string, KnowledgePathNode>();

  for (const directory of data.directories) {
    for (const source of directory.files) {
      const windows = /^[a-z]:[\\/]|^\\\\/i.test(source);
      const normalized = windows ? source.replace(/\\/g, "/") : source;
      const drive = normalized.match(/^([a-z]):\//i);
      const share = windows ? normalized.match(/^\/\/[^/]+\/[^/]+/) : null;
      const root = drive ? `${drive[1].toUpperCase()}:/` : share ? `${share[0]}/` : normalized.startsWith("/") ? "/" : "";
      const parts = normalized.slice(root.length).split("/").filter(Boolean);
      if (!parts.length) continue;

      const separator = windows ? "\\" : "/";
      const displayPath = (path: string) => windows ? path.replace(/\//g, separator) : path;
      const rootKey = `directory:${windows ? root.toLowerCase() : root}`;
      let parent = nodes.get(rootKey);
      if (!parent) {
        parent = { key: rootKey, name: displayPath(root) || ".", path: displayPath(root) || ".", isLeaf: false, children: [] };
        nodes.set(rootKey, parent);
        roots.push(parent);
      }

      let path = root;
      for (const [index, name] of parts.entries()) {
        path += `${path && !path.endsWith("/") ? "/" : ""}${name}`;
        const isLeaf = index === parts.length - 1;
        const key = `${isLeaf ? "file" : "directory"}:${windows ? path.toLowerCase() : path}`;
        let node = nodes.get(key);
        if (!node) {
          node = { key, name, path: isLeaf ? source : displayPath(path), isLeaf, ...(!isLeaf && { children: [] }) };
          nodes.set(key, node);
          parent.children?.push(node);
        }
        parent = node;
      }
    }
  }

  const sort = (items: KnowledgePathNode[]) => {
    items.sort((a, b) => Number(a.isLeaf) - Number(b.isLeaf) || a.name.localeCompare(b.name, "zh-CN", { numeric: true }));
    items.forEach((node) => { if (node.children) sort(node.children); });
  };
  sort(roots);
  const compact = (node: KnowledgePathNode, separator: string): KnowledgePathNode => {
    let result = node;
    while (result.children?.length === 1 && !result.children[0].isLeaf) {
      const child = result.children[0];
      result = { ...child, name: `${result.name}${separator}${child.name}` };
    }
    if (result.children) result.children = result.children.map((child) => compact(child, separator));
    return result;
  };
  for (const root of roots) {
    const separator = root.name.includes("\\") ? "\\" : "/";
    root.children = root.children?.map((node) => compact(node, separator));
  }
  return roots;
}
