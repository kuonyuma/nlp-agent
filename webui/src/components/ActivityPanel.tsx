import { Brain, CheckCircle2, ChevronDown, CircleAlert, LoaderCircle, Search, Users } from "lucide-react";
import { useState } from "react";

import type { ActivityItem } from "@/lib/types";

const icons = { thinking: Brain, tool: Search, worker: Users, recovery: CircleAlert };

export function ActivityPanel({ activities, reasoning, showReasoning }: {
  activities: ActivityItem[];
  reasoning?: string;
  showReasoning: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!activities.length && !reasoning) return null;
  const running = activities.some((item) => item.status === "running");
  return (
    <div className="activity-panel">
      <button type="button" className="activity-trigger" onClick={() => setOpen((value) => !value)}>
        {running ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}
        <span>{running ? "正在组织教学内容" : "处理过程"}</span>
        <ChevronDown size={14} className={open ? "rotate" : ""} />
      </button>
      {open && (
        <div className="activity-list">
          {activities.map((item) => {
            const Icon = icons[item.kind];
            return <div className={`activity-row ${item.status}`} key={item.id}><Icon size={14} /><span>{item.label}</span></div>;
          })}
          {showReasoning && reasoning && (
            <details className="reasoning-detail">
              <summary>查看模型思考内容</summary>
              <pre>{reasoning}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
