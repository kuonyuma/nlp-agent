import { ArrowUp, GraduationCap, Square } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

import type { RuntimeModelProfile } from "@/shared/types";

const prompts = ["用简单语言解释", "举一个实际例子", "逐步推导", "对比两个概念", "出一道练习题", "检查我的答案"];

export function Composer({ disabled, running, centered = false, onSend, onCancel, contextControl, modelProfiles = {}, modelProfile, onModelProfileChange }: {
  disabled: boolean;
  running: boolean;
  centered?: boolean;
  onSend: (content: string) => void;
  onCancel: () => void;
  contextControl?: ReactNode;
  modelProfiles?: Record<string, RuntimeModelProfile>;
  modelProfile?: string;
  onModelProfileChange?: (modelProfile: string) => void;
}) {
  const [content, setContent] = useState("");
  const sendValue = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || disabled || running) return;
    setContent("");
    onSend(trimmed);
  };
  const submit = () => sendValue(content);
  const submitPrompt = (prompt: string) => {
    const existing = content.trim();
    sendValue(existing ? `${existing}\n${prompt}` : prompt);
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  return <div className={`composer-wrap ${centered ? "centered" : ""}`}>
    <div className="quick-prompts">{prompts.map((prompt) => <button key={prompt} type="button" onClick={() => submitPrompt(prompt)} disabled={disabled || running}>{prompt}</button>)}</div>
    <div className="composer">
      <textarea value={content} onChange={(event) => setContent(event.target.value)} onKeyDown={keyDown} disabled={disabled} rows={centered ? 3 : 1} placeholder="问一个 NLP 问题……" aria-label="学习问题" />
      <div className="composer-toolbar">
        <span><GraduationCap size={15} />Nova · LSNU NLP Learning Agent</span>
        {modelProfile && onModelProfileChange && Object.keys(modelProfiles).length > 0 && <select className="model-profile-select" aria-label="选择模型" value={modelProfile} disabled={disabled || running} onChange={(event) => onModelProfileChange(event.target.value)}>
          {Object.entries(modelProfiles).map(([value, profile]) => <option key={value} value={value} disabled={!profile.available}>{profile.label}{profile.available ? "" : "（不可用）"}</option>)}
        </select>}
        {contextControl}
        {running ? <button className="send-button stop" type="button" onClick={onCancel} aria-label="停止生成"><Square size={14} fill="currentColor" /></button> : <button className="send-button" type="button" onClick={submit} disabled={disabled || !content.trim()} aria-label="发送"><ArrowUp size={18} /></button>}
      </div>
    </div>
    <p className="composer-hint">Nova 也可能犯错，重要结论请结合教材验证</p>
  </div>;
}
