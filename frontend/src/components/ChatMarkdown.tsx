import { CodeHighlighter } from "@ant-design/x";
import { XMarkdown, type ComponentProps } from "@ant-design/x-markdown";
import { theme } from "antd";
import type { ReactNode } from "react";
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
  return (
    <XMarkdown
      className="chat-markdown"
      components={markdownComponents}
      content={content}
      openLinksInNewTab
      streaming={{
        enableAnimation: true,
        hasNextChunk: streaming,
        tail: streaming,
      }}
    />
  );
}
