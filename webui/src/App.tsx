import { BookOpenCheck, ChevronRight, PanelRight, Wifi, WifiOff } from "lucide-react";
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
  const [learningOpen, setLearningOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const activeTitle = workspace.activeMeta.title ?? "新的学习对话";
  const statusText = {
    connected: "已连接",
    connecting: "正在连接",
    reconnecting: "正在恢复连接",
    offline: "离线",
  }[workspace.socketStatus];
  const statusOnline = workspace.socketStatus === "connected";
  const archived = useMemo(() => workspace.sessions.filter((session) => workspace.preferences.sessions[session.session_id]?.archived), [workspace.preferences.sessions, workspace.sessions]);

  if (workspace.bootStatus === "loading") {
    return <div className="boot-screen"><span className="boot-orbit" /><strong>正在进入 NLP 学习空间</strong><p>连接教学 Agent 与学习记录…</p></div>;
  }
  if (workspace.bootStatus === "error") {
    return <div className="boot-screen error"><WifiOff size={28} /><strong>暂时无法连接后端</strong><p>{workspace.error}</p><button type="button" onClick={() => location.reload()}>重新连接</button></div>;
  }

  return (
    <div className="app-shell">
      <Sidebar
        sessions={workspace.sessions}
        preferences={workspace.preferences}
        activeId={workspace.activeSessionId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelect={workspace.setActiveSessionId}
        onCreate={() => void workspace.createSession()}
        onMeta={workspace.updateSessionMeta}
        onDelete={(id) => { if (confirm("删除后将同时清除后端对话记录，确定继续吗？")) void workspace.deleteSession(id); }}
        onSettings={() => setSettingsOpen(true)}
        onDeveloper={() => { location.href = "/developer"; }}
        onTeacher={() => { location.href = "/teacher"; }}
      />
      <main className="thread-shell">
        <header className="thread-header">
          <SidebarToggle onClick={() => setSidebarOpen(true)} />
          <div className="thread-title"><strong>{activeTitle}</strong><span className={statusOnline ? "online" : ""}>{statusOnline ? <Wifi size={12} /> : <WifiOff size={12} />}{statusText}</span></div>
          <button className="learning-panel-button" type="button" onClick={() => setLearningOpen(true)}><BookOpenCheck size={16} /><span>学习记录</span><ChevronRight size={14} /></button>
          <button className="icon-button panel-icon" type="button" aria-label="打开学习记录" onClick={() => setLearningOpen(true)}><PanelRight size={18} /></button>
        </header>
        <LearningContextBar value={workspace.preferences.context} onChange={(context) => {
          workspace.setLearningContext(context);
          if (workspace.activeSessionId) workspace.updateSessionMeta(workspace.activeSessionId, { topic: context.topic });
        }} />
        <div className="thread-scroll">
          <MessageList messages={workspace.messages} loading={workspace.loadingMessages} showReasoning={workspace.settings.show_reasoning} onFollowUp={(text) => void workspace.send(text)} />
        </div>
        <Composer disabled={workspace.socketStatus !== "connected"} running={workspace.isRunning} onSend={(text) => void workspace.send(text)} onCancel={workspace.cancel} />
      </main>
      <LearningPanel open={learningOpen} onClose={() => setLearningOpen(false)} title={activeTitle} context={workspace.preferences.context} meta={workspace.activeMeta} messages={workspace.messages} onPrompt={(content) => { setLearningOpen(false); void workspace.send(content); }} onMeta={(patch) => { if (workspace.activeSessionId) workspace.updateSessionMeta(workspace.activeSessionId, patch); }} />
      {learningOpen && <button className="learning-backdrop" type="button" aria-label="关闭学习记录" onClick={() => setLearningOpen(false)} />}
      <SettingsDialog open={settingsOpen} settings={workspace.settings} onClose={() => setSettingsOpen(false)} onChange={(patch) => void workspace.patchSettings(patch)} />
      {archived.length > 0 && <span className="sr-only">已归档 {archived.length} 个学习对话</span>}
    </div>
  );
}
