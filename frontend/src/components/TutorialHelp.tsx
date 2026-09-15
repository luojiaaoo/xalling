import { QuestionCircleOutlined } from "@ant-design/icons";
import { Anchor, Button, Dropdown, Modal } from "antd";
import { useEffect, useRef, useState } from "react";

import {
  getTutorial,
  listTutorials,
  type TutorialDocument,
  type TutorialSummary,
} from "../bridge/client";
import { ChatMarkdown } from "./ChatMarkdown";

type TocItem = {
  key: string;
  href: string;
  title: string;
};

/** 标题栏 "?" 教程入口：下拉列出本地教程，点击弹窗展示 Markdown 内容 */
export function TutorialHelp() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [tutorials, setTutorials] = useState<TutorialSummary[]>([]);
  const [tutorialDoc, setTutorialDoc] = useState<TutorialDocument | null>(null);
  const [toc, setToc] = useState<TocItem[]>([]);
  const contentRef = useRef<HTMLDivElement>(null);

  // 每次展开菜单时重新读取教程列表，新增教程文件后无需重启应用
  const handleMenuOpenChange = async (nextOpen: boolean) => {
    setMenuOpen(nextOpen);
    if (nextOpen) {
      setTutorials(await listTutorials());
    }
  };

  const openTutorial = async (tutorialId: string) => {
    setMenuOpen(false);
    setTutorialDoc(await getTutorial(tutorialId));
  };

  // 提取标题生成导航目录：弹窗首次打开时内容可能尚未挂载、XMarkdown 也是异步渲染，
  // 所以先用 rAF 重试等容器出现，再用 MutationObserver 等标题渲染出来后补上锚点 id
  useEffect(() => {
    if (tutorialDoc === null) {
      return;
    }
    let cancelled = false;
    let observer: MutationObserver | null = null;

    const extractToc = (container: HTMLElement) => {
      const items: TocItem[] = [];
      container.querySelectorAll("h1, h2, h3").forEach((node, index) => {
        const id = `tutorial-heading-${index}`;
        node.id = id;
        items.push({ key: id, href: `#${id}`, title: node.textContent ?? "" });
      });
      // 内容没变时保持原引用，避免 MutationObserver 触发的无限重渲染
      setToc((prev) =>
        prev.length === items.length && prev.every((item, i) => item.title === items[i].title)
          ? prev
          : items,
      );
    };

    const attach = () => {
      if (cancelled) {
        return;
      }
      const container = contentRef.current;
      if (container === null) {
        requestAnimationFrame(attach);
        return;
      }
      extractToc(container);
      observer = new MutationObserver(() => extractToc(container));
      observer.observe(container, { childList: true, subtree: true });
    };
    attach();

    return () => {
      cancelled = true;
      observer?.disconnect();
    };
  }, [tutorialDoc]);

  return (
    <>
      <Dropdown
        open={menuOpen}
        onOpenChange={(nextOpen) => void handleMenuOpenChange(nextOpen)}
        trigger={["click"]}
        placement="bottomRight"
        menu={{
          items:
            tutorials.length > 0
              ? tutorials.map((tutorial) => ({ key: tutorial.id, label: tutorial.title }))
              : [{ key: "__empty__", label: "暂无教程", disabled: true }],
          onClick: ({ key }) => void openTutorial(key),
        }}
      >
        <Button type="text" icon={<QuestionCircleOutlined />} aria-label="教程" />
      </Dropdown>
      <Modal
        open={tutorialDoc !== null}
        title={tutorialDoc?.title}
        footer={null}
        width={860}
        className="tutorial-modal"
        onCancel={() => setTutorialDoc(null)}
      >
        {tutorialDoc !== null && (
          <div className="tutorial-body">
            <div className="tutorial-content" ref={contentRef}>
              <ChatMarkdown content={tutorialDoc.content} />
            </div>
            {toc.length > 1 && (
              <Anchor
                className="tutorial-toc"
                affix={false}
                replace
                items={toc}
                getContainer={() => contentRef.current as HTMLElement}
              />
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
