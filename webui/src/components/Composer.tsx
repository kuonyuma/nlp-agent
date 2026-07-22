import { ArrowUp, GraduationCap, Square } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

const prompts = ["用简单语言解释", "举一个实际例子", "逐步推导", "对比两个概念", "出一道练习题", "检查我的答案"];

export function Composer({ disabled, running, centered = false, onSend, onCancel, contextControl }: {
  disabled: boolean;
  running: boolean;
  centered?: boolean;
  onSend: (content: string) => void;
  onCancel: () => void;
  contextControl?: ReactNode;
}) {
  const [content, setContent] = useState("");
  const submit = () => {
    const value = content.trim();
    if (!value || disabled || running) return;
    setContent("");
    onSend(value);
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  return <div className={`composer-wrap ${centered ? "centered" : ""}`}>
    <div className="quick-prompts">{prompts.map((prompt) => <button key={prompt} type="button" onClick={() => setContent((value) => value ? `${value}\n${prompt}` : prompt)}>{prompt}</button>)}</div>
    <div className="composer">
      <textarea value={content} onChange={(event) => setContent(event.target.value)} onKeyDown={keyDown} disabled={disabled} rows={centered ? 3 : 1} placeholder="问一个 NLP 问题……" aria-label="学习问题" />
      <div className="composer-toolbar"><span><GraduationCap size={15} />Nova · LSNU NLP Learning Agent</span>{contextControl}{running ? <button className="send-button stop" type="button" onClick={onCancel} aria-label="停止生成"><Square size={14} fill="currentColor" /></button> : <button className="send-button" type="button" onClick={submit} disabled={disabled || !content.trim()} aria-label="发送"><ArrowUp size={18} /></button>}</div>
    </div>
    <p className="composer-hint">Nova 也可能犯错，重要结论请结合教材验证</p>
  </div>;
}
