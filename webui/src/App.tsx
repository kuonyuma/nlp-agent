import { BookOpenCheck, Moon, Sun, Wifi, WifiOff } from "lucide-react";
import { useMemo, useState } from "react";

import { Composer } from "@/components/Composer";
import { LearningContextBar } from "@/components/LearningContextBar";
import { LearningPanel } from "@/components/LearningPanel";
import { MessageList } from "@/components/MessageList";
import { SettingsDialog } from "@/components/SettingsDialog";
import { Sidebar, SidebarToggle } from "@/components/Sidebar";
import { DeveloperWorkspace } from "@/components/developer/DeveloperWorkspace";
import { TeacherWorkspace } from "@/components/teacher/TeacherWorkspace";
import { useStudentWorkspace } from "@/hooks/useStudentWorkspace";

export function App() {
  if (location.pathname.startsWith("/developer")) return <DeveloperWorkspace />;
  if (location.pathname.startsWith("/teacher")) return <TeacherWorkspace />;
  return <StudentApp />;
}

function StudentApp() {
  const workspace = useStudentWorkspace();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem("nlp.sidebar.collapsed") === "true");
  const [learningOpen, setLearningOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const activeTitle = workspace.activeMeta.title ?? "新的学习对话";
  const statusText = { connected: "已连接", connecting: "正在连接", reconnecting: "正在恢复连接", offline: "离线" }[workspace.socketStatus];
  const statusOnline = workspace.socketStatus === "connected";
  const hasMessages = workspace.loadingMessages || workspace.messages.length > 0;
  const archived = useMemo(() => workspace.sessions.filter((session) => workspace.preferences.sessions[session.session_id]?.archived), [workspace.preferences.sessions, workspace.sessions]);
  const setCollapsed = (collapsed: boolean) => { setSidebarCollapsed(collapsed); localStorage.setItem("nlp.sidebar.collapsed", String(collapsed)); };

  if (workspace.bootStatus === "loading") return <div className="boot-screen"><span className="boot-orbit" /><strong>正在进入 NLP 学习空间</strong><p>连接教学 Agent 与学习记录……</p></div>;
  if (workspace.bootStatus === "error") return <div className="boot-screen error"><WifiOff size={28} /><strong>暂时无法连接后端</strong><p>{workspace.error}</p><button type="button" onClick={() => location.reload()}>重新连接</button></div>;

  const updateContext = (context: typeof workspace.preferences.context) => {
    workspace.setLearningContext(context);
    if (workspace.activeSessionId) workspace.updateSessionMeta(workspace.activeSessionId, { topic: context.topic });
  };
  const composer = (centered = false) => <Composer centered={centered} disabled={!statusOnline} running={workspace.isRunning} onSend={(text) => void workspace.send(text)} onCancel={workspace.cancel} />;

  return <div className="app-shell">
    <Sidebar sessions={workspace.sessions} preferences={workspace.preferences} activeId={workspace.activeSessionId} open={sidebarOpen} collapsed={sidebarCollapsed} connected={statusOnline} onClose={() => setSidebarOpen(false)} onCollapse={() => setCollapsed(true)} onExpand={() => setCollapsed(false)} onSelect={workspace.setActiveSessionId} onCreate={() => void workspace.createSession()} onMeta={workspace.updateSessionMeta} onDelete={(id) => { if (confirm("删除后将同时清除后端对话记录，确定继续吗？")) void workspace.deleteSession(id); }} onSettings={() => setSettingsOpen(true)} />
    <main className="thread-shell">
      <header className="thread-header">
        <SidebarToggle onClick={() => { setCollapsed(false); setSidebarOpen(true); }} />
        {hasMessages ? <div className="thread-title"><strong>{activeTitle}</strong><span className={statusOnline ? "online" : ""}>{statusOnline ? <Wifi size={12} /> : <WifiOff size={12} />}{statusText}</span></div> : <div className="thread-title" />}
        <button className="icon-button theme-toggle" type="button" aria-label="切换主题" onClick={() => void workspace.patchSettings({ theme: workspace.settings.theme === "dark" ? "light" : "dark" })}>{workspace.settings.theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
      </header>
      <LearningContextBar value={workspace.preferences.context} onChange={updateContext} />
      {hasMessages ? <><div className="thread-scroll"><MessageList messages={workspace.messages} loading={workspace.loadingMessages} showReasoning={workspace.settings.show_reasoning} onFollowUp={(text) => void workspace.send(text)} /></div>{composer()}</> : <div className="empty-thread-home"><div><h1>今天想学习什么？</h1><p>从一个 NLP 概念、模型原理或练习问题开始。</p>{composer(true)}</div></div>}
    </main>
    <div className={`learning-hover-zone ${learningOpen ? "open" : ""}`} onMouseEnter={() => setLearningOpen(true)} onMouseLeave={() => setLearningOpen(false)} onFocus={() => setLearningOpen(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setLearningOpen(false); }}>
      <button className="learning-rail-button" type="button" aria-label="学习记录" onClick={() => setLearningOpen((value) => !value)}><BookOpenCheck size={17} /><span>学习记录</span></button>
      <LearningPanel open={learningOpen} onClose={() => setLearningOpen(false)} title={activeTitle} context={workspace.preferences.context} meta={workspace.activeMeta} messages={workspace.messages} onPrompt={(content) => { setLearningOpen(false); void workspace.send(content); }} onMeta={(patch) => { if (workspace.activeSessionId) workspace.updateSessionMeta(workspace.activeSessionId, patch); }} />
    </div>
    {learningOpen && <button className="learning-backdrop" type="button" aria-label="关闭学习记录" onClick={() => setLearningOpen(false)} />}
    <SettingsDialog open={settingsOpen} settings={workspace.settings} learningContext={workspace.preferences.context} onClose={() => setSettingsOpen(false)} onChange={(patch) => void workspace.patchSettings(patch)} onLearningContextChange={workspace.setLearningContext} onOpenDeveloper={() => { location.href = "/developer"; }} onOpenTeacher={() => { location.href = "/teacher"; }} />
    {archived.length > 0 && <span className="sr-only">已归档 {archived.length} 个学习对话</span>}
  </div>;
}
