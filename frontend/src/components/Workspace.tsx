import { Bubble } from "@ant-design/x";
import { useState } from "react";

import { QuickActions } from "./QuickActions";
import { TaskComposer } from "./TaskComposer";

const starterBubbles = [
  { key: "assistant-ready", role: "assistant" as const, content: "我已准备好协助你规划、执行和复盘任务。" },
];

export function Workspace() {
  const [prompt, setPrompt] = useState("");

  return (
    <main className="workspace">
      <div className="watermark" aria-hidden="true">X</div>
      <div className="workspace-content">
        <div className="eyebrow">XALLING · AI WORKSPACE</div>
        <h1>下午好呀，接下来交给我吧</h1>
        <p className="subtitle">从一个想法开始，把复杂工作变得清晰、可执行。</p>
        <TaskComposer prompt={prompt} onPromptChange={setPrompt} />
        <QuickActions onSelect={(label) => setPrompt(`帮我完成${label}`)} />
        <div className="assistant-ready" aria-label="助手状态">
          <Bubble.List items={starterBubbles} />
        </div>
      </div>
    </main>
  );
}
