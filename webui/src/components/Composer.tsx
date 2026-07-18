import { ArrowUp, Square } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

const prompts = ["用简单语言解释", "举一个实际例子", "逐步推导", "对比两个概念", "出一道练习题", "检查我的答案"];

export function Composer({ disabled, running, onSend, onCancel }: {
  disabled: boolean;
  running: boolean;
  onSend: (content: string) => void;
  onCancel: () => void;
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
  return (
    <div className="composer-wrap">
      <div className="quick-prompts">
        {prompts.map((prompt) => <button key={prompt} type="button" onClick={() => setContent((value) => value ? `${value}\n${prompt}` : prompt)}>{prompt}</button>)}
      </div>
      <div className="composer">
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={keyDown}
          disabled={disabled}
          rows={1}
          placeholder="输入你的 NLP 问题…"
          aria-label="学习问题"
        />
        {running ? (
          <button className="send-button stop" type="button" onClick={onCancel} aria-label="停止生成"><Square size={14} fill="currentColor" /></button>
        ) : (
          <button className="send-button" type="button" onClick={submit} disabled={disabled || !content.trim()} aria-label="发送"><ArrowUp size={18} /></button>
        )}
      </div>
      <p className="composer-hint">Enter 发送，Shift + Enter 换行 · AI 可能犯错，请结合教材验证重要结论</p>
    </div>
  );
}
