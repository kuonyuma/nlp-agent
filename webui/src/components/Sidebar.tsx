import { Archive, BookOpen, GraduationCap, Heart, Menu, MoreHorizontal, Pencil, Plus, Search, Settings, Trash2, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { deriveTitle } from "@/lib/learning-preferences";
import type { LearningPreferences, SessionLearningMeta, SessionSummary } from "@/lib/types";

export function Sidebar({ sessions, preferences, activeId, open, collapsed, connected, onClose, onCollapse, onExpand, onSelect, onCreate, onMeta, onDelete, onSettings }: {
  sessions: SessionSummary[];
  preferences: LearningPreferences;
  activeId: string | null;
  open: boolean;
  collapsed: boolean;
  connected: boolean;
  onClose: () => void;
  onCollapse: () => void;
  onExpand: () => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onMeta: (id: string, patch: Partial<SessionLearningMeta>) => void;
  onDelete: (id: string) => void;
  onSettings: () => void;
}) {
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
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

  return <>
    {open && <button className="sidebar-backdrop" type="button" aria-label="关闭侧栏" onClick={onClose} />}
    <aside className={`sidebar ${open ? "open" : ""} ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-brand">
        <button className="brand-mark" type="button" aria-label={collapsed ? "展开侧栏" : "NLP 学习助手"} onClick={collapsed ? onExpand : undefined}><GraduationCap size={19} /></button>
        {!collapsed && <><strong>NLP 学习助手</strong><button className="icon-button collapse-button" type="button" aria-label="折叠侧栏" onClick={onCollapse}><Menu size={16} /></button><button className="mobile-only icon-button" type="button" onClick={onClose}><X size={18} /></button></>}
      </div>
      <nav className="sidebar-actions">
        <SideAction collapsed={collapsed} label="新建对话" icon={<Plus size={18} />} onClick={onCreate} />
        <SideAction collapsed={collapsed} label="搜索" icon={<Search size={18} />} onClick={() => { if (collapsed) onExpand(); setSearchOpen((value) => !value); }} />
        {!!sessions.some((session) => preferences.sessions[session.session_id]?.archived) && <SideAction collapsed={collapsed} label={showArchived ? "返回最近对话" : "归档对话"} icon={<Archive size={18} />} onClick={() => { if (collapsed) onExpand(); setShowArchived((value) => !value); }} />}
      </nav>
      {!collapsed && searchOpen && <div className="search-box"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索历史问题" /></div>}
      <div className="session-scroll">
        {!collapsed && grouped.map(([topic, items]) => <section className="session-group" key={topic}>
          <h3><BookOpen size={13} />{topic}</h3>
          {items.map((session) => {
            const meta = preferences.sessions[session.session_id] ?? {};
            return <div className={`session-item ${activeId === session.session_id ? "active" : ""}`} key={session.session_id}>
              <button className="session-main" type="button" onClick={() => { onSelect(session.session_id); onClose(); }}><span>{meta.title ?? "新的学习对话"}</span></button>
              <details className="session-menu"><summary aria-label="会话菜单"><MoreHorizontal size={16} /></summary><div>
                <button type="button" onClick={() => { const title = prompt("重命名学习对话", meta.title ?? ""); if (title?.trim()) onMeta(session.session_id, { title: title.trim() }); }}><Pencil size={14} />重命名</button>
                <button type="button" onClick={() => onMeta(session.session_id, { favorite: !meta.favorite })}><Heart size={14} />{meta.favorite ? "取消收藏" : "收藏"}</button>
                <button type="button" onClick={() => onMeta(session.session_id, { archived: !meta.archived })}><Archive size={14} />{meta.archived ? "移出归档" : "归档"}</button>
                <button className="danger" type="button" onClick={() => onDelete(session.session_id)}><Trash2 size={14} />删除</button>
              </div></details>
              {meta.favorite && <Heart className="favorite-mark" size={11} fill="currentColor" />}
            </div>;
          })}
        </section>)}
        {!collapsed && !visible.length && <p className="sidebar-empty">{showArchived ? "暂无归档对话" : "还没有学习记录"}</p>}
      </div>
      <div className="sidebar-footer"><SideAction collapsed={collapsed} label="设置" icon={<Settings size={18} />} onClick={onSettings} /><i className={`connection-dot ${connected ? "online" : ""}`} title={connected ? "已连接" : "连接中"} /></div>
    </aside>
  </>;
}

function SideAction({ collapsed, label, icon, onClick }: { collapsed: boolean; label: string; icon: ReactNode; onClick: () => void }) {
  return <button type="button" className="side-action" title={collapsed ? label : undefined} aria-label={label} onClick={onClick}><span>{icon}</span>{!collapsed && <b>{label}</b>}</button>;
}

export function SidebarToggle({ onClick }: { onClick: () => void }) {
  return <button className="icon-button sidebar-toggle" type="button" onClick={onClick} aria-label="打开侧栏"><Menu size={18} /></button>;
}
