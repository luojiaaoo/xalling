import { DownloadOutlined, HddOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Modal, Spin, Tree } from "antd";
import type { TreeDataNode } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  downloadKnowledgeEmbedding,
  getKnowledgeEmbeddingStatus,
  getKnowledgeTree,
  type KnowledgeEmbeddingStatus,
  type KnowledgeTree,
} from "../api/client";
import { buildKnowledgeTree, type KnowledgePathNode } from "../knowledge/tree";

function toTreeNode(node: KnowledgePathNode, root = false): TreeDataNode {
  return {
    key: node.key,
    title: <span className={root ? "knowledge-node-name knowledge-root-name" : "knowledge-node-name"} title={node.path}>{node.name}</span>,
    isLeaf: node.isLeaf,
    ...(root && { icon: <HddOutlined /> }),
    ...(node.children && { children: node.children.map((child) => toTreeNode(child)) }),
  };
}

function KnowledgePanel() {
  const [data, setData] = useState<KnowledgeTree | null>(null);
  const [model, setModel] = useState<KnowledgeEmbeddingStatus | null>(null);
  const [downloadPending, setDownloadPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const mounted = useRef(false);

  const refresh = useCallback(async () => {
    const current = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const status = await getKnowledgeEmbeddingStatus();
      if (current !== requestId.current) return;
      setModel(status);
      if (status.status === "ready") {
        const result = await getKnowledgeTree();
        if (current === requestId.current) setData(result);
      } else {
        setData(null);
      }
    } catch (reason) {
      if (current === requestId.current) setError(reason instanceof Error ? reason.message : "读取知识库失败");
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; requestId.current += 1; };
  }, [refresh]);

  useEffect(() => {
    if (model?.status !== "downloading") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await refresh();
      if (!cancelled) timer = setTimeout(() => void poll(), 1500);
    };
    timer = setTimeout(() => void poll(), 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [model?.status, refresh]);

  const download = async () => {
    if (downloadPending || !model || model.status === "downloading") return;
    setDownloadPending(true);
    setError(null);
    setModel({ ...model, status: "downloading", message: "正在下载并验证嵌入模型，完成后即可使用知识库。" });
    try {
      await downloadKnowledgeEmbedding();
      if (mounted.current) await refresh();
    } catch (reason) {
      if (mounted.current) {
        await refresh();
        if (mounted.current) setError(reason instanceof Error ? reason.message : "下载嵌入模型失败");
      }
    } finally {
      if (mounted.current) setDownloadPending(false);
    }
  };

  const roots = useMemo(() => data ? buildKnowledgeTree(data).map((node) => toTreeNode(node, true)) : [], [data]);

  return <div className="knowledge-panel">
    <div className="knowledge-toolbar">
      <p className="knowledge-scope">所有工作区共享。此处只读展示已入库文件的原路径，可在对话中指定目录或让 AI 语义查找文件。</p>
      <Button icon={<ReloadOutlined />} aria-label="刷新知识库" loading={loading} onClick={() => void refresh()} />
    </div>
    {error && error !== model?.message && <Alert type="error" title={error} showIcon />}
    {model && <Alert
      type={model.status === "ready" ? "success" : model.status === "error" ? "error" : model.status === "downloading" ? "info" : "warning"}
      title={model.status === "ready" ? "嵌入模型已就绪" : model.status === "downloading" ? "正在准备嵌入模型" : "知识库尚未启用"}
      description={model.message}
      showIcon
      action={model.status !== "ready" && <Button
        type="primary"
        icon={<DownloadOutlined />}
        loading={downloadPending || model.status === "downloading"}
        onClick={() => void download()}
      >{model.status === "downloading" ? "下载中" : "下载嵌入模型"}</Button>}
    />}
    {loading && !data && !model ? <div className="knowledge-loading"><Spin /></div> : model?.status !== "ready" ? null : roots.length ?
      <div className="knowledge-forest">
        {roots.map((root) => <Tree.DirectoryTree
          key={root.key}
          className="knowledge-tree"
          treeData={[root]}
          selectable={false}
          blockNode
          virtual={false}
        />)}
      </div> :
      <Empty description="暂无知识库资料，可在对话中让 AI 导入文档" />}
  </div>;
}

export function Knowledge({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal title="本地知识库" open={open} onCancel={onClose} footer={null} width={1000} destroyOnHidden>
    <KnowledgePanel />
  </Modal>;
}
