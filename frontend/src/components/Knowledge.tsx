import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Modal, Spin, Tree } from "antd";
import type { TreeDataNode } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { getKnowledgeTree, type KnowledgeTree } from "../api/client";

function KnowledgePanel() {
  const [data, setData] = useState<KnowledgeTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    const current = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await getKnowledgeTree();
      if (current === requestId.current) setData(result);
    } catch (reason) {
      if (current === requestId.current) setError(reason instanceof Error ? reason.message : "读取知识库失败");
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => { requestId.current += 1; };
  }, [refresh]);

  const nodes: TreeDataNode[] = data?.directories.map((directory) => ({
    key: `directory:${directory.path}`,
    title: <strong className="knowledge-file-path">{directory.path}</strong>,
    children: directory.files.map((path) => ({
      key: `file:${path}`, title: <span className="knowledge-file-path">{path}</span>, isLeaf: true,
    })),
  })) ?? [];

  return <div className="knowledge-panel">
    <div className="knowledge-toolbar">
      <p className="knowledge-scope">所有工作区共享。此处只读展示已入库文件的原路径，可在对话中指定目录或让 AI 语义查找文件。</p>
      <Button icon={<ReloadOutlined />} aria-label="刷新知识库" loading={loading} onClick={() => void refresh()} />
    </div>
    {error && <Alert type="error" title={error} showIcon />}
    {loading && !data ? <div className="knowledge-loading"><Spin /></div> : nodes.length ?
      <Tree className="knowledge-tree" treeData={nodes} selectable={false} defaultExpandAll showLine virtual={false} /> :
      <Empty description="暂无知识库资料，可在对话中让 AI 导入文档" />}
  </div>;
}

export function Knowledge({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal title="本地知识库" open={open} onCancel={onClose} footer={null} width={1000} destroyOnHidden>
    <KnowledgePanel />
  </Modal>;
}
