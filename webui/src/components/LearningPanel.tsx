import { BookMarked, Download, Lightbulb, Target, X } from "lucide-react";

import type { ChatMessage, LearningContext, SessionLearningMeta } from "@/lib/types";

function downloadReport(title: string, context: LearningContext, meta: SessionLearningMeta, messages: ChatMessage[]) {
  const body = [
    `# ${title}`,
    "",
    `- 学习主题：${meta.topic ?? context.topic}`,
    `- 学习难度：${context.level}`,
    `- 教学模式：${context.mode}`,
    "",
    meta.summary ? `## 学习摘要\n\n${meta.summary}\n` : "",
    "## 对话记录",
    ...messages.map((message) => `\n### ${message.role === "user" ? "学生" : "NLP 教师"}\n\n${message.content}`),
  ].join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([body], { type: "text/markdown;charset=utf-8" }));
  link.download = `${title || "NLP学习报告"}.md`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function LearningPanel({ open, onClose, title, context, meta, messages, onPrompt }: {
  open: boolean;
  onClose: () => void;
  title: string;
  context: LearningContext;
  meta: SessionLearningMeta;
  messages: ChatMessage[];
  onPrompt: (content: string) => void;
}) {
  const answered = messages.filter((message) => message.role === "assistant" && message.status === "completed").length;
  const progress = Math.min(100, answered * 20 + (meta.concepts?.length ?? 0) * 5);
  return (
    <aside className={`learning-panel ${open ? "open" : ""}`}>
      <header><div><BookMarked size={17} /><strong>本次学习</strong></div><button className="icon-button" type="button" onClick={onClose}><X size={17} /></button></header>
      <section><h3><Target size={15} />学习目标</h3><p>理解并能够运用“{meta.topic ?? context.topic}”相关概念，通过讲解、示例与练习建立完整认识。</p></section>
      <section><h3><Lightbulb size={15} />已涉及概念</h3><div className="concept-list">{meta.concepts?.length ? meta.concepts.map((concept) => <span key={concept}>{concept}</span>) : <small>完成一次对话后自动整理</small>}</div></section>
      <section><h3><Target size={15} />学习进度</h3><div className="progress-track"><span style={{ width: `${progress}%` }} /></div><p>本次对话完成度约 {progress}% · {answered} 次有效讲解</p></section>
      <section><h3><BookMarked size={15} />对话摘要</h3><p>{meta.summary || "尚未生成学习摘要。"}</p></section>
      <section className="practice-card"><h3><Lightbulb size={15} />巩固练习</h3><p>让教学 Agent 根据当前内容出题，或检查你自己的理解。</p><div><button type="button" onClick={() => onPrompt("请根据刚才的内容出一道练习题，先不要给答案。")}>生成练习</button><button type="button" onClick={() => onPrompt("请用三个问题检查我是否真正理解了当前知识点。")}>检查理解</button></div></section>
      <button className="export-button" type="button" disabled={!messages.length} onClick={() => downloadReport(title, context, meta, messages)}><Download size={15} />导出 Markdown 学习报告</button>
    </aside>
  );
}
