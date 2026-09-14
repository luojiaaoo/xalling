import { SearchOutlined } from "@ant-design/icons";
import { Input } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { searchChatSessions, type ChatSearchMatch } from "../bridge/client";

/** 把摘要里命中的关键词包上 <mark>，大小写不敏感。 */
function renderSearchSnippet(snippet: string, query: string): ReactNode {
  const keyword = query.trim();
  if (!keyword) {
    return snippet;
  }
  const lowerSnippet = snippet.toLowerCase();
  const lowerKeyword = keyword.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let found = lowerSnippet.indexOf(lowerKeyword, cursor);
  while (found >= 0) {
    if (found > cursor) {
      parts.push(snippet.slice(cursor, found));
    }
    parts.push(<mark key={parts.length}>{snippet.slice(found, found + keyword.length)}</mark>);
    cursor = found + keyword.length;
    found = lowerSnippet.indexOf(lowerKeyword, cursor);
  }
  parts.push(snippet.slice(cursor));
  return parts;
}

type SearchPaletteProps = {
  onClose: () => void;
  onOpenResult: (sessionId: string, messageKey: string | null) => void;
  currentSessionId?: string | null;
};

/** 居中悬浮的会话搜索面板：输入即搜，↑↓ 选择，Enter 打开并定位到消息气泡。 */
export function SearchPalette({ onClose, onOpenResult, currentSessionId = null }: SearchPaletteProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChatSearchMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const requestRef = useRef(0);
  const resultsRef = useRef<HTMLDivElement>(null);

  // 输入停顿 250ms 后再搜，丢弃过期响应，避免旧结果覆盖新结果
  useEffect(() => {
    const keyword = query.trim();
    if (!keyword) {
      setResults([]);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    const timer = window.setTimeout(() => {
      const requestId = ++requestRef.current;
      void searchChatSessions(keyword)
        .then((matches) => {
          if (requestRef.current !== requestId) {
            return;
          }
          setResults(matches);
          setActiveIndex(0);
        })
        .catch(() => {
          if (requestRef.current === requestId) {
            setResults([]);
          }
        })
        .finally(() => {
          if (requestRef.current === requestId) {
            setLoading(false);
          }
        });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  // ↑↓ 移动选中行时，让选中行始终滚进结果列表可视区
  useEffect(() => {
    resultsRef.current
      ?.querySelector(".search-result-row-active")
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  // 当前会话的结果置顶，其余保持后端返回的「最近修改在前」顺序（sort 稳定，不改组内相对顺序）
  const orderedResults = useMemo(() => {
    if (!currentSessionId) {
      return results;
    }
    return [...results].sort((left, right) => {
      const leftCurrent = left.session_id === currentSessionId ? 0 : 1;
      const rightCurrent = right.session_id === currentSessionId ? 0 : 1;
      return leftCurrent - rightCurrent;
    });
  }, [currentSessionId, results]);

  // 挂在面板容器上：输入框和结果按钮获得焦点时都能响应按键
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, orderedResults.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const match = orderedResults[activeIndex];
      if (match) {
        onOpenResult(match.session_id, match.message_key);
      }
    } else if (event.key === "Escape") {
      onClose();
    }
  }

  return (
    <div className="search-palette-mask" onClick={onClose}>
      <div
        className="search-palette"
        role="dialog"
        aria-label="搜索历史会话"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="search-palette-input-row">
          <Input
            allowClear
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话标题和内容…"
            prefix={<SearchOutlined />}
            size="large"
            value={query}
            variant="borderless"
          />
        </div>
        <div ref={resultsRef} className="search-palette-results">
          {loading && <div className="search-palette-status">正在搜索…</div>}
          {!loading && query.trim() && !orderedResults.length && (
            <div className="search-palette-status">没有匹配的会话</div>
          )}
          {!query.trim() && (
            <div className="search-palette-status">搜索历史会话的标题和消息内容</div>
          )}
          {orderedResults.map((match, index) => (
            <button
              key={`${match.session_id}:${match.message_key ?? "title"}`}
              className={`search-result-row${
                index === activeIndex ? " search-result-row-active" : ""
              }`}
              type="button"
              onClick={() => onOpenResult(match.session_id, match.message_key)}
              onMouseEnter={() => setActiveIndex(index)}
            >
              <span className="search-result-title-row">
                <span className="search-result-title">{match.title}</span>
                <span className="search-result-tags">
                  {match.session_id === currentSessionId && (
                    <em className="search-result-tag search-result-tag-current">当前会话</em>
                  )}
                  <em className="search-result-tag search-result-tag-project">{match.project_name}</em>
                </span>
              </span>
              <span className="search-result-snippet">
                <em className="search-result-role">
                  {match.role === "user" ? "我" : match.role === "assistant" ? "AI" : "标题"}
                </em>
                {renderSearchSnippet(match.snippet, query)}
              </span>
            </button>
          ))}
        </div>
        <div className="search-palette-footer">
          <span><kbd>enter</kbd> 选择</span>
          <span><kbd>↑</kbd> <kbd>↓</kbd> 上下切换</span>
          <span><kbd>esc</kbd> 关闭面板</span>
        </div>
      </div>
    </div>
  );
}
