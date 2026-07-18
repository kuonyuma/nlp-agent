import { Check, Copy, GraduationCap, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ActivityPanel } from "./ActivityPanel";
import { MarkdownContent } from "./MarkdownContent";
import type { ChatMessage } from "@/lib/types";

function AssistantMessage({ message, showReasoning, onFollowUp }: {
  message: ChatMessage;
  showReasoning: boolean;
  onFollowUp: (text: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const streaming = ["accepted", "running"].includes(message.status ?? "");
  const copy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <article className="assistant-message">
      <div className="assistant-mark"><GraduationCap size={17} /></div>
      <div className="assistant-body">
        <ActivityPanel activities={message.activities ?? []} reasoning={message.reasoning} showReasoning={showReasoning} />
        {message.status === "failed" ? (
          <div className="error-card">这次讲解没有完成，请稍后重试。</div>
        ) : message.status === "cancelled" && !message.content ? (
          <div className="muted-card">已停止生成。</div>
        ) : (
          <MarkdownContent streaming={streaming}>{message.content}</MarkdownContent>
        )}
        {!streaming && message.content && (
          <div className="message-actions">
            <button type="button" onClick={copy}>{copied ? <Check size={15} /> : <Copy size={15} />} {copied ? "已复制" : "复制"}</button>
            <button type="button" onClick={() => onFollowUp("请换一种更容易理解的方式重新解释。") }><RotateCcw size={15} /> 换种讲法</button>
          </div>
        )}
      </div>
    </article>
  );
}

export function MessageList({ messages, loading, showReasoning, onFollowUp }: {
  messages: ChatMessage[];
  loading: boolean;
  showReasoning: boolean;
  onFollowUp: (text: string) => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages]);
  if (loading) return <div className="empty-state"><span className="loading-dot" />正在加载学习记录…</div>;
  if (!messages.length) {
    return (
      <div className="hero-state">
        <div className="hero-icon"><GraduationCap size={30} /></div>
        <h2>今天想学习什么？</h2>
        <p>可以询问 NLP 概念、公式推导、模型原理，也可以让我出题并检查答案。</p>
      </div>
    );
  }
  return (
    <div className="message-list">
      {messages.map((message) => message.role === "user" ? (
        <div className="user-message" key={message.id}>{message.content}</div>
      ) : (
        <AssistantMessage key={message.id} message={message} showReasoning={showReasoning} onFollowUp={onFollowUp} />
      ))}
      <div ref={bottom} />
    </div>
  );
}
