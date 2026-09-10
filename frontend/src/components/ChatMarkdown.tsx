import { CodeHighlighter } from "@ant-design/x";
import { XMarkdown, type ComponentProps } from "@ant-design/x-markdown";
import { theme } from "antd";
import { useMemo, type ReactNode } from "react";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

function MarkdownPre({ children }: ComponentProps) {
  return <>{children}</>;
}

function MarkdownCode({ block, children, lang }: ComponentProps) {
  const { token } = theme.useToken();
  const code = String(children ?? "").replace(/\n$/, "");
  if (!block) {
    return <code className="markdown-inline-code">{children as ReactNode}</code>;
  }

  const darkMode = token.colorBgBase === "#000" || token.colorBgBase === "#000000";
  return (
    <CodeHighlighter
      className="markdown-code-highlighter"
      classNames={{ header: "markdown-code-header", code: "markdown-code-body" }}
      lang={lang ?? "text"}
      prismLightMode={false}
      highlightProps={{
        style: darkMode ? oneDark : oneLight,
        customStyle: { margin: 0, padding: 14, background: "transparent" },
      }}
    >
      {code}
    </CodeHighlighter>
  );
}

const markdownComponents = {
  pre: MarkdownPre,
  code: MarkdownCode,
};

type ChatMarkdownProps = {
  content: string;
  streaming?: boolean;
};

export function ChatMarkdown({ content, streaming = false }: ChatMarkdownProps) {
  // x-markdown 2.9.0 的 enableAnimation 会触发无限重渲染导致 React #185 白屏
  // （ant-design/x#1958，官方已修复但未发布），修复版本发布后恢复 enableAnimation: true。
  // 配置对象用 useMemo 保持引用稳定，避免 XMarkdown 内部 memo 失效。
  const streamingConfig = useMemo(
    () => ({ hasNextChunk: streaming, tail: streaming }),
    [streaming],
  );
  return (
    <XMarkdown
      className="chat-markdown"
      components={markdownComponents}
      content={content}
      openLinksInNewTab
      streaming={streamingConfig}
    />
  );
}
