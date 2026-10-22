import { DeleteOutlined, DownloadOutlined, HddOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, App, Button, Empty, Modal, Spin, Tree } from "antd";
import type { TreeDataNode } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  deleteKnowledgeDocuments,
  downloadKnowledgeEmbedding,
  getKnowledgeEmbeddingStatus,
  getKnowledgeTree,
  type KnowledgeEmbeddingStatus,
  type KnowledgeTree,
} from "../api/client";
import { buildKnowledgeTree, collectKnowledgeSources, type KnowledgePathNode } from "../knowledge/tree";

function toTreeNode(node: KnowledgePathNode, onDelete: (node: KnowledgePathNode) => void, deleting: boolean, root = false): TreeDataNode {
  return {
    key: node.key,
    title: <span className="knowledge-node-label">
      <span className={root ? "knowledge-node-name knowledge-root-name" : "knowledge-node-name"} title={node.path}>{node.name}</span>
      {!root && <Button
        className="knowledge-node-delete"
        type="text"
        size="small"
        danger
        icon={<DeleteOutlined />}
        aria-label={`删除${node.isLeaf ? "文档" : "文件夹下的文档"}：${node.path}`}
        title={node.isLeaf ? "从知识库删除文档" : "从知识库删除此文件夹下的全部文档"}
        disabled={deleting}
        onClick={(event) => { event.stopPropagation(); onDelete(node); }}
        onDoubleClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") event.stopPropagation(); }}
      />}
    </span>,
    isLeaf: node.isLeaf,
    ...(root && { icon: <HddOutlined /> }),
    ...(node.children && { children: node.children.map((child) => toTreeNode(child, onDelete, deleting)) }),
  };
}

function KnowledgePanel() {
  const { message } = App.useApp();
  const [data, setData] = useState<KnowledgeTree | null>(null);
  const [model, setModel] = useState<KnowledgeEmbeddingStatus | null>(null);
  const [downloadPending, setDownloadPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ node: KnowledgePathNode; sources: string[] } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deletePending = useRef(false);
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

  const selectDelete = useCallback((node: KnowledgePathNode) => {
    if (deletePending.current) return;
    setDeleteError(null);
    setDeleteTarget({ node, sources: collectKnowledgeSources(node) });
  }, []);

  const remove = async () => {
    if (!deleteTarget || deletePending.current) return;
    deletePending.current = true;
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await deleteKnowledgeDocuments(deleteTarget.sources);
      if (!mounted.current) return;
      setDeleteTarget(null);
      const removed = new Set(deleteTarget.sources);
      setData((previous) => previous && ({ directories: previous.directories.map((directory) => ({
        ...directory, files: directory.files.filter((path) => !removed.has(path)),
      })) }));
      void message.success(`已从知识库删除 ${result.deleted} 个文档`);
      await refresh();
    } catch (reason) {
      if (mounted.current) setDeleteError(reason instanceof Error ? reason.message : "删除文档失败，请重试");
    } finally {
      deletePending.current = false;
      if (mounted.current) setDeleting(false);
    }
  };

  const roots = useMemo(() => data ? buildKnowledgeTree(data).map((node) => toTreeNode(node, selectDelete, deleting, true)) : [], [data, selectDelete, deleting]);

  return <div className="knowledge-panel">
    <div className="knowledge-toolbar">
      <p className="knowledge-scope">所有工作区共享。可在对话中指定目录或让 AI 语义查找文件；删除仅移除知识库文档，保留磁盘原文件。</p>
      <Button icon={<ReloadOutlined />} aria-label="刷新知识库" loading={loading} disabled={deleting} onClick={() => void refresh()} />
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
    <Modal
      title={deleteTarget?.node.isLeaf ? "从知识库删除文档？" : "删除文件夹下的全部知识库文档？"}
      open={deleteTarget !== null}
      onCancel={() => { if (!deletePending.current) setDeleteTarget(null); }}
      onOk={() => void remove()}
      okText="删除文档"
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !deleteTarget?.sources.length }}
      cancelButtonProps={{ disabled: deleting }}
      confirmLoading={deleting}
      closable={!deleting}
      keyboard={!deleting}
      mask={{ closable: !deleting }}
    >
      <p className="knowledge-delete-path">{deleteTarget?.node.path}</p>
      <p>将删除 {deleteTarget?.sources.length ?? 0} 个已入库文档及其检索索引，保留磁盘原文件。</p>
      <ul className="knowledge-delete-sources" aria-label="将删除的知识库文档">
        {deleteTarget?.sources.map((path) => <li key={path}>{path}</li>)}
      </ul>
      {deleteError && <Alert type="error" title={deleteError} showIcon />}
    </Modal>
  </div>;
}

export function Knowledge({ open, onClose }: { open: boolean; onClose: () => void }) {
  return <Modal title="本地知识库" open={open} onCancel={onClose} footer={null} width={1000} destroyOnHidden>
    <KnowledgePanel />
  </Modal>;
}
