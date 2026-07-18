import { Archive, BookOpen, Code2, GraduationCap, Heart, Menu, MoreHorizontal, Pencil, Plus, Presentation, Search, Settings, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { deriveTitle } from "@/lib/learning-preferences";
import type { LearningPreferences, SessionLearningMeta, SessionSummary } from "@/lib/types";

function formatTime(timestamp?: number | string): string {
  if (!timestamp) return "";
  const date = typeof timestamp === "number" ? new Date(timestamp * 1000) : new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

export function Sidebar({ sessions, preferences, activeId, open, onClose, onSelect, onCreate, onMeta, onDelete, onSettings, onDeveloper, onTeacher }: {
  sessions: SessionSummary[];
  preferences: LearningPreferences;
  activeId: string | null;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onMeta: (id: string, patch: Partial<SessionLearningMeta>) => void;
  onDelete: (id: string) => void;
  onSettings: () => void;
  onDeveloper: () => void;
  onTeacher: () => void;
}) {
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const visible = useMemo(() => sessions.filter((session) => {
    const meta = preferences.sessions[session.session_id];
    if (!!meta?.archived !== showArchived) return false;
    const title = meta?.title ?? deriveTitle(session.session_id);
    return title.toLowerCase().includes(query.toLowerCase());
  }), [preferences.sessions, query, sessions, showArchived]);
  const grouped = useMemo(() => {
    const groups: Record<string, SessionSummary[]> = {};
    for (const session of visible) {
      const topic = preferences.sessions[session.session_id]?.topic ?? "未分类";
      (groups[topic] ??= []).push(session);
    }
    return Object.entries(groups);
  }, [preferences.sessions, visible]);
  return (
    <>
      {open && <button className="sidebar-backdrop" type="button" aria-label="关闭侧栏" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-brand"><div className="brand-mark"><GraduationCap size={18} /></div><strong>NLP 学习助手</strong><button className="mobile-only icon-button" type="button" onClick={onClose}><X size={18} /></button></div>
        <button className="new-chat" type="button" onClick={onCreate}><Plus size={17} />新的学习对话</button>
        <div className="search-box"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索历史问题" /></div>
        <div className="session-scroll">
          {grouped.map(([topic, items]) => (
            <section className="session-group" key={topic}>
              <h3><BookOpen size={13} />{topic}</h3>
              {items?.map((session) => {
                const meta = preferences.sessions[session.session_id] ?? {};
                return (
                  <div className={`session-item ${activeId === session.session_id ? "active" : ""}`} key={session.session_id}>
                    <button className="session-main" type="button" onClick={() => { onSelect(session.session_id); onClose(); }}>
                      <span>{meta.title ?? "新的学习对话"}</span><small>{formatTime(session.last_active)}</small>
                    </button>
                    <details className="session-menu"><summary aria-label="会话菜单"><MoreHorizontal size={16} /></summary><div>
                      <button type="button" onClick={() => { const title = prompt("重命名学习对话", meta.title ?? ""); if (title?.trim()) onMeta(session.session_id, { title: title.trim() }); }}><Pencil size={14} />重命名</button>
                      <button type="button" onClick={() => onMeta(session.session_id, { favorite: !meta.favorite })}><Heart size={14} />{meta.favorite ? "取消收藏" : "收藏"}</button>
                      <button type="button" onClick={() => onMeta(session.session_id, { archived: !meta.archived })}><Archive size={14} />{meta.archived ? "移出归档" : "归档"}</button>
                      <button className="danger" type="button" onClick={() => onDelete(session.session_id)}><Trash2 size={14} />删除</button>
                    </div></details>
                    {meta.favorite && <Heart className="favorite-mark" size={11} fill="currentColor" />}
                  </div>
                );
              })}
            </section>
          ))}
          {!visible.length && <p className="sidebar-empty">{showArchived ? "暂无归档对话" : "还没有学习记录"}</p>}
        </div>
        <div className="sidebar-footer">
          <button type="button" onClick={() => setShowArchived((value) => !value)}><Archive size={16} />{showArchived ? "返回最近对话" : "查看归档"}</button>
          <button type="button" onClick={onSettings}><Settings size={16} />偏好设置</button>
          <button type="button" onClick={onDeveloper}><Code2 size={16} />开发者模式</button>
          <button type="button" onClick={onTeacher}><Presentation size={16} />教师模式</button>
        </div>
      </aside>
    </>
  );
}

export function SidebarToggle({ onClick }: { onClick: () => void }) {
  return <button className="icon-button sidebar-toggle" type="button" onClick={onClick} aria-label="打开侧栏"><Menu size={18} /></button>;
}
