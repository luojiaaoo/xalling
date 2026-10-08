import { Button } from "antd";
import { useMemo, useState } from "react";

import { parseUnifiedDiff, splitDiffLines, type DiffLine } from "../chat/file-diff";
import "./DiffViewer.css";

function prefix(line: DiffLine): string {
  return line.kind === "add" ? "+" : line.kind === "remove" ? "−" : " ";
}

export function DiffViewer({ patch }: { patch: string }) {
  const [mode, setMode] = useState<"unified" | "split">("unified");
  const parsed = useMemo(() => parseUnifiedDiff(patch), [patch]);
  const split = useMemo(() => splitDiffLines(parsed.lines), [parsed]);
  return (
    <div className="diff-viewer">
      <div className="diff-viewer-controls" aria-label="差异显示方式">
        <Button size="small" type={mode === "unified" ? "primary" : "text"} aria-pressed={mode === "unified"} onClick={() => setMode("unified")}>统一视图</Button>
        <Button size="small" type={mode === "split" ? "primary" : "text"} aria-pressed={mode === "split"} onClick={() => setMode("split")}>并排视图</Button>
      </div>
      {parsed.truncated && <div className="diff-preview-limit" role="status">预览仅显示前 5000 行，请在编辑器中查看完整差异。</div>}
      <div className="diff-viewer-scroll" tabIndex={0} aria-label="文件差异">
        <table className={`diff-viewer-table ${mode}`} aria-label={mode === "split" ? "并排文件差异" : "统一文件差异"}>
          {mode === "split" && <>
            <colgroup><col className="diff-number-column" /><col /><col className="diff-number-column" /><col /></colgroup>
            <thead><tr><th colSpan={2}>修改前</th><th colSpan={2}>修改后</th></tr></thead>
          </>}
          <tbody>
            {mode === "unified" ? parsed.lines.map((line, index) => (
              line.kind === "meta" ? (
                <tr key={index} className="diff-meta"><td colSpan={4}>{line.text}</td></tr>
              ) : (
                <tr key={index} className={`diff-${line.kind}`}>
                  <td className="diff-line-number">{line.oldLine}</td>
                  <td className="diff-line-number">{line.newLine}</td>
                  <td className="diff-prefix">{prefix(line)}</td>
                  <td className="diff-code">{line.text || " "}</td>
                </tr>
              )
            )) : split.map((row, index) => (
              row.meta !== undefined ? (
                <tr key={index} className="diff-meta"><td colSpan={4}>{row.meta}</td></tr>
              ) : (
                <tr key={index}>
                  <td className="diff-line-number">{row.left?.oldLine}</td>
                  <td className={`diff-code diff-${row.left?.kind ?? "empty"}`}>{row.left ? `${prefix(row.left)} ${row.left.text}` : " "}</td>
                  <td className="diff-line-number">{row.right?.newLine}</td>
                  <td className={`diff-code diff-${row.right?.kind ?? "empty"}`}>{row.right ? `${prefix(row.right)} ${row.right.text}` : " "}</td>
                </tr>
              )
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
