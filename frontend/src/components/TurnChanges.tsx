import { DownOutlined, FileTextOutlined, UpOutlined } from "@ant-design/icons";
import { Button, Modal } from "antd";
import { useState } from "react";

import type { ChatRenderEvent, TurnFileChange } from "../api/client";
import { DiffViewer } from "./DiffViewer";
import { FileCheckpointAction } from "./FileCheckpointAction";
import "./TurnChanges.css";

type Props = {
  files: TurnFileChange[];
  checkpointId?: string;
  filesRestoredAt?: string;
  disabled: boolean;
  projectPath: string | null;
  sessionId: string;
  onRestored: (event: ChatRenderEvent) => void;
  onRestoringChange: (restoring: boolean) => void;
};

function displayPath(path: string, project: string | null): string {
  const normalized = path.replaceAll("\\", "/");
  const prefix = project?.replaceAll("\\", "/").replace(/\/$/, "");
  if (!prefix) return normalized;
  const windows = /^[a-z]:\//i.test(prefix);
  const matches = windows ? normalized.toLowerCase().startsWith(`${prefix.toLowerCase()}/`) : normalized.startsWith(`${prefix}/`);
  return matches ? normalized.slice(prefix.length + 1) : normalized;
}

function Counts({ additions, deletions }: { additions: number | null; deletions: number | null }) {
  return additions === null || deletions === null ? <span className="turn-change-unknown">行数未知</span> : (
    <span className="turn-change-counts"><span className="added">+{additions}</span><span className="removed">-{deletions}</span></span>
  );
}

export function TurnChanges(props: Props) {
  const { files, projectPath } = props;
  const [expanded, setExpanded] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const selected = files.find((file) => file.path === selectedPath);
  const partial = files.some((file) => file.additions === null || file.deletions === null);
  const hasCounts = files.some((file) => file.additions !== null && file.deletions !== null);
  const additions = files.reduce((total, file) => total + (file.additions ?? 0), 0);
  const deletions = files.reduce((total, file) => total + (file.deletions ?? 0), 0);
  return (
    <section className="turn-changes" aria-label="本轮文件修改">
      <div className="turn-changes-header">
        <FileTextOutlined />
        <div className="turn-changes-summary">
          <strong>已修改 {files.length} 个文件</strong>
          <div><Counts additions={hasCounts ? additions : null} deletions={hasCounts ? deletions : null} />{partial && hasCounts && <span className="turn-change-unknown"> 部分行数未知</span>}</div>
        </div>
        <div className="turn-changes-actions">
          {props.checkpointId && files.some((file) => file.restorable) && (
            <FileCheckpointAction
              checkpointId={props.checkpointId}
              disabled={props.disabled}
              filesRestoredAt={props.filesRestoredAt}
              projectPath={projectPath}
              sessionId={props.sessionId}
              onRestored={props.onRestored}
              onRestoringChange={props.onRestoringChange}
              label={props.filesRestoredAt ? "再次恢复" : "撤销修改"}
            />
          )}
          <Button size="small" onClick={() => setSelectedPath(files[0]?.path ?? null)}>查看变更</Button>
        </div>
      </div>
      {props.filesRestoredAt && <div className="turn-changes-restored" role="status">已恢复到本轮开始前；以下保留本轮修改记录</div>}
      <div className="turn-changes-files">
        {(expanded ? files : files.slice(0, 4)).map((file) => (
          <button type="button" className="turn-change-row" key={file.path} title={file.path} onClick={() => setSelectedPath(file.path)}>
            <span className="turn-change-path">{displayPath(file.path, projectPath)}</span>
            <Counts additions={file.additions} deletions={file.deletions} />
          </button>
        ))}
      </div>
      {files.length > 4 && <button type="button" className="turn-changes-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? <>收起文件 <UpOutlined /></> : <>再显示 {files.length - 4} 个文件 <DownOutlined /></>}
      </button>}
      <Modal
        title="本轮文件修改"
        open={selectedPath !== null}
        onCancel={() => setSelectedPath(null)}
        footer={null}
        width="min(1100px, calc(100vw - 48px))"
        className="turn-changes-modal"
        destroyOnHidden
      >
        <div className="turn-changes-review">
          <nav className="turn-changes-navigation" aria-label="本轮修改的文件">
            {files.map((file) => <button type="button" key={file.path} className={`turn-change-row${file.path === selectedPath ? " selected" : ""}`}
              aria-current={file.path === selectedPath ? "true" : undefined} title={file.path} onClick={() => setSelectedPath(file.path)}>
              <span className="turn-change-path">{displayPath(file.path, projectPath)}</span>
              <Counts additions={file.additions} deletions={file.deletions} />
            </button>)}
          </nav>
          <div className="turn-changes-diff">
            <div className="turn-changes-diff-title">{selected && displayPath(selected.path, projectPath)}</div>
            {selected?.partial && <div className="turn-changes-note">SDK 未提供完整的修改前后内容，显示已记录的逐次修改，无法计算净增删行数。</div>}
            {selected?.truncated && <div className="turn-changes-note">差异过大，预览已截断。</div>}
            {selected?.patch ? <DiffViewer key={selected.path} patch={selected.patch} /> : <div className="turn-changes-note">此文件没有可展示的文本差异。</div>}
          </div>
        </div>
      </Modal>
    </section>
  );
}
