import { useState } from "react";

import { pickQuote } from "../quotes";
import { TaskComposer } from "./TaskComposer";
import { TitleBar } from "./TitleBar";

/** 各时段的问候语，随机抽一条，避免每次打开都一样。 */
const greetingsByPeriod: string[][] = [
  // 凌晨 0-5 点：以安慰为主
  [
    "凌晨好呀，夜深了，别太拼，慢慢来。",
    "凌晨好呀，这么晚还醒着，辛苦了，剩下的交给我。",
    "凌晨好呀，安静的深夜适合专注，但也记得照顾自己。",
  ],
  // 清晨 6-7 点：早起加油
  [
    "早上好呀，这么早就开始啦，新的一天一起加油！",
    "早上好呀，清晨的你已经很棒了，今天会是好日子。",
    "早上好呀，早起的鸟儿有虫吃，我们一起加油！",
  ],
  // 上午 8-10 点
  [
    "早上好呀，元气满满的上午，正适合开工。",
    "早上好呀，带着好心情出发吧。",
    "早上好呀，今天也要闪闪发光。",
  ],
  // 中午 11-12 点
  [
    "中午好呀，忙碌了一上午，记得好好吃饭。",
    "中午好呀，歇口气，下午继续冲。",
    "中午好呀，吃饱了才有力气改变世界。",
  ],
  // 下午 13-17 点
  [
    "下午好呀，午后时光，稳稳推进就好。",
    "下午好呀，离目标又近了一步，继续加油。",
    "下午好呀，来杯咖啡，把剩下的交给我。",
  ],
  // 晚上 18-23 点：以放松为主
  [
    "晚上好呀，忙了一天辛苦了，放轻松。",
    "晚上好呀，今晚就别太操劳啦，剩下的交给我。",
    "晚上好呀，愿今晚的效率与好心情同在。",
  ],
];

function getGreeting(hour: number): string {
  const period =
    hour < 6 ? 0 : hour < 8 ? 1 : hour < 11 ? 2 : hour < 13 ? 3 : hour < 18 ? 4 : 5;
  const options = greetingsByPeriod[period];
  return options[Math.floor(Math.random() * options.length)];
}

export function Workspace() {
  const [prompt, setPrompt] = useState("");
  const [quote] = useState(pickQuote);
  const greeting = getGreeting(new Date().getHours());

  return (
    <main className="workspace">
      <TitleBar />
      <div className="watermark" aria-hidden="true">X</div>
      <div className="workspace-content">
        <div className="eyebrow">XALLING · AI WORKSPACE</div>
        <h1>{greeting}</h1>
        <p className="subtitle">{quote}</p>
        <TaskComposer prompt={prompt} onPromptChange={setPrompt} />
      </div>
    </main>
  );
}
