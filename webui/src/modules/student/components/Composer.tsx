import { ArrowUp, GraduationCap, Square, Paperclip } from "lucide-react";
import { useState, useRef, type KeyboardEvent, type ReactNode } from "react";

import { uploadAttachment } from "@/platform/http/api";
import type { RuntimeModelProfile, ChatAttachment } from "@/shared/types";

const prompts = ["用简单语言解释", "举一个实际例子", "逐步推导", "对比两个概念", "出一道练习题", "检查我的答案"];

export function Composer({ sessionId, disabled, running, centered = false, onSend, onCancel, contextControl, modelProfiles = {}, modelProfile, onModelProfileChange }: {
  sessionId?: string | null;
  disabled: boolean;
  running: boolean;
  centered?: boolean;
  onSend: (content: string, attachments?: ChatAttachment[]) => void;
  onCancel: () => void;
  contextControl?: ReactNode;
  modelProfiles?: Record<string, RuntimeModelProfile>;
  modelProfile?: string;
  onModelProfileChange?: (modelProfile: string) => void;
}) {
  const [content, setContent] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const sendValue = (value: string) => {
    const trimmed = value.trim();
    if ((!trimmed && attachments.length === 0) || disabled || running) return;
    setContent("");
    const readyAttachments = attachments.filter((a) => a.status === "ready");
    if (readyAttachments.length > 0) {
      onSend(trimmed, readyAttachments);
    } else {
      onSend(trimmed);
    }
    setAttachments([]);
  };
  const submit = () => sendValue(content);
  const submitPrompt = (prompt: string) => {
    // Preserve any in-progress input by appending the preset on a new line,
    // then flow through the shared sendValue path for trim/guard handling.
    const existing = content.trim();
    sendValue(existing ? `${existing}\n${prompt}` : prompt);
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !sessionId) return;
    event.target.value = "";
    
    const newAttachment: ChatAttachment = {
      fileName: file.name,
      url: URL.createObjectURL(file),
      mediaType: file.type,
      width: 0,
      height: 0,
      status: "uploading",
    };
    
    setAttachments((prev) => [...prev, newAttachment]);
    
    try {
      const res = await uploadAttachment(sessionId, file);
      setAttachments((prev) => prev.map((a) => a.fileName === file.name ? { ...a, url: res.url, width: res.width, height: res.height, status: "ready" } : a));
    } catch {
      setAttachments((prev) => prev.map((a) => a.fileName === file.name ? { ...a, status: "error", errorMessage: "上传失败" } : a));
    }
  };

  return <div className={`composer-wrap ${centered ? "centered" : ""}`}>
    <div className="quick-prompts">{prompts.map((prompt) => <button key={prompt} type="button" onClick={() => submitPrompt(prompt)} disabled={disabled || running}>{prompt}</button>)}</div>
    <div className="composer">
      {attachments.length > 0 && (
        <div className="composer-attachments" style={{ display: "flex", gap: "8px", padding: "8px", borderBottom: "1px solid var(--border)", overflowX: "auto" }}>
          {attachments.map((att, i) => (
            <div key={i} className="attachment-thumbnail" style={{ position: "relative", display: "inline-block" }}>
              <img src={att.url} alt={att.fileName} style={{ width: 60, height: 60, objectFit: "cover", opacity: att.status === "uploading" ? 0.5 : 1, borderRadius: "4px" }} />
              {att.status === "error" && <span style={{ color: "red", position: "absolute", bottom: 0, left: 0, fontSize: "10px", background: "rgba(255,255,255,0.8)", padding: "2px" }}>失败</span>}
            </div>
          ))}
        </div>
      )}
      <textarea value={content} onChange={(event) => setContent(event.target.value)} onKeyDown={keyDown} disabled={disabled} rows={centered ? 3 : 1} placeholder="问一个 NLP 问题……" aria-label="学习问题" />
      <div className="composer-toolbar">
        <span><GraduationCap size={15} />Nova · LSNU NLP Learning Agent</span>
        {modelProfile && onModelProfileChange && Object.keys(modelProfiles).length > 0 && <select className="model-profile-select" aria-label="选择模型" value={modelProfile} disabled={disabled || running} onChange={(event) => onModelProfileChange(event.target.value)}>
          {Object.entries(modelProfiles).map(([value, profile]) => <option key={value} value={value} disabled={!profile.available}>{profile.label}{profile.available ? "" : "（不可用）"}</option>)}
        </select>}
        {contextControl}
        <input type="file" ref={fileInputRef} hidden accept="image/jpeg,image/png,image/webp" onChange={handleFileSelect} />
        <button type="button" className="attachment-button" style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: "4px", display: "flex", alignItems: "center" }} onClick={() => fileInputRef.current?.click()} disabled={disabled || running || !sessionId} aria-label="上传附件"><Paperclip size={18} /></button>
        {running ? <button className="send-button stop" type="button" onClick={onCancel} aria-label="停止生成"><Square size={14} fill="currentColor" /></button> : <button className="send-button" type="button" onClick={submit} disabled={disabled || (!content.trim() && attachments.length === 0)} aria-label="发送"><ArrowUp size={18} /></button>}
      </div>
    </div>
    <p className="composer-hint">Nova 也可能犯错，重要结论请结合教材验证</p>
  </div>;
}
