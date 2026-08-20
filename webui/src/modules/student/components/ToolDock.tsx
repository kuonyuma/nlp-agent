import { BookOpenCheck, FileText, Globe2, Plus, Terminal, X } from "lucide-react";
import type { ReactNode } from "react";

export type ToolDockTool = "files" | "learning" | "browser" | "terminal";

const tools: Array<{
  id: ToolDockTool;
  label: string;
  buttonLabel: string;
  shortcut: string;
  icon: typeof FileText;
  description: string;
}> = [
  { id: "files", label: "文件", buttonLabel: "打开文件工具", shortcut: "Ctrl+P", icon: FileText, description: "代码工作区将在这里打开。" },
  { id: "learning", label: "学习记录", buttonLabel: "打开学习记录工具", shortcut: "Ctrl+Alt+S", icon: BookOpenCheck, description: "查看本次对话的学习目标、概念与进度。" },
  { id: "browser", label: "浏览器", buttonLabel: "打开浏览器工具", shortcut: "Ctrl+T", icon: Globe2, description: "后续可在这里安全查看学习资料与网页。" },
  { id: "terminal", label: "终端", buttonLabel: "打开终端工具", shortcut: "Ctrl+~", icon: Terminal, description: "代码沙箱接入后将在这里显示终端与运行输出。" },
];

function EmptyToolPanel({ tool }: { tool: Exclude<ToolDockTool, "learning"> }) {
  const item = tools.find((candidate) => candidate.id === tool)!;
  const Icon = item.icon;
  return <section className="tool-dock-empty-panel">
    <span><Icon size={20} /></span>
    <strong>{item.label}</strong>
    <p>{item.description}</p>
  </section>;
}

export function ToolDock({ open, openTools, activeTool, onOpenChange, onOpenTool, onCloseTool, onActiveToolChange, learningPanel }: {
  open: boolean;
  openTools: ToolDockTool[];
  activeTool: ToolDockTool | null;
  onOpenChange: (open: boolean) => void;
  onOpenTool: (tool: ToolDockTool) => void;
  onCloseTool: (tool: ToolDockTool) => void;
  onActiveToolChange: (tool: ToolDockTool | null) => void;
  learningPanel: ReactNode;
}) {
  return <aside className={["tool-dock", open && "open"].filter(Boolean).join(" ")} aria-label="工具侧栏">
    {open && <div className="tool-dock-surface">
      <header className="tool-dock-tabs" role="tablist" aria-label="已打开的工具">
        {openTools.length ? openTools.map((tool) => {
          const item = tools.find((candidate) => candidate.id === tool)!;
          const Icon = item.icon;
          const selected = tool === activeTool;
          return <div key={tool} className={["tool-dock-tab", selected && "active"].filter(Boolean).join(" ")}>
            <button type="button" role="tab" aria-selected={selected} onClick={() => onActiveToolChange(tool)}><Icon size={15} /><span>{item.label}</span></button>
            <button type="button" aria-label={"关闭" + item.label} onClick={() => onCloseTool(tool)}><X size={14} /></button>
          </div>;
        }) : <span className="tool-dock-tab-placeholder">工具</span>}
        <button className="tool-dock-add-tab" type="button" aria-label="显示工具列表" onClick={() => onActiveToolChange(null)}><Plus size={16} /></button>
        <button className="tool-dock-close" type="button" aria-label="关闭工具侧栏" onClick={() => onOpenChange(false)}><X size={17} /></button>
      </header>
      {activeTool === "learning" ? learningPanel : activeTool ? <EmptyToolPanel tool={activeTool} /> : <nav className="tool-dock-home" aria-label="工具列表">
        {tools.map((item) => {
          const Icon = item.icon;
          return <button key={item.id} type="button" aria-label={item.buttonLabel} onClick={() => onOpenTool(item.id)}>
            <span><Icon size={18} /></span>
            <strong>{item.label}</strong>
            <kbd>{item.shortcut}</kbd>
          </button>;
        })}
      </nav>}
    </div>}
  </aside>;
}
