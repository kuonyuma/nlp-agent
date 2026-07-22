import { Brain, CheckCircle2, ChevronDown, CircleAlert, LoaderCircle, Search, Users, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ActivityItem } from "@/lib/types";

const icons = { thinking: Brain, tool: Wrench, worker: Users, recovery: CircleAlert } as const;

function elapsedSeconds(from?: string, until?: string, now = Date.now()) {
  const started = from ? Date.parse(from) : NaN;
  const ended = until ? Date.parse(until) : now;
  if (!Number.isFinite(started) || !Number.isFinite(ended)) return 0;
  return Math.max(0, Math.round((ended - started) / 1000));
}

function durationLabel(seconds: number) { return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`; }

export function ActivityPanel({ activities, reasoning, showReasoning, running, startedAt: turnStartedAt, completedAt: turnCompletedAt }: {
  activities: ActivityItem[];
  reasoning?: string;
  showReasoning: boolean;
  running: boolean;
  startedAt?: string;
  completedAt?: string;
}) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const validActivities = useMemo(() => activities.filter((item): item is ActivityItem => !!item && typeof item.label === "string" && typeof item.status === "string"), [activities]);
  const activityRunning = validActivities.some((item) => item.status === "running");
  const startedAt = turnStartedAt ?? validActivities.map((item) => item.startedAt).filter((value): value is string => !!value).sort()[0];
  const completedAt = turnCompletedAt ?? validActivities.map((item) => item.completedAt).filter((value): value is string => !!value).sort().at(-1);
  const seconds = elapsedSeconds(startedAt, running ? undefined : completedAt, now);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [running]);
  if (!validActivities.length && !reasoning) return null;
  const expanded = running || activityRunning || open;

  return <section className="activity-panel" aria-label="处理过程">
    <button type="button" className="activity-trigger" aria-expanded={expanded} onClick={() => setOpen((value) => !value)}>
      {running ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}
      <span>{running ? `运行中 · ${durationLabel(seconds)}` : `已处理 ${durationLabel(seconds)}`}</span>
      <ChevronDown size={14} className={expanded ? "rotate" : ""} />
    </button>
    {expanded && <div className="activity-list" role="list">
      {validActivities.map((item, index) => {
        const Icon = icons[item.kind] ?? Search;
        return <div className={`activity-row ${item.status}`} key={`${item.id}:${index}`} role="listitem"><Icon size={14} /><span>{item.label}</span>{item.detail && <small>{item.detail}</small>}</div>;
      })}
      {showReasoning && reasoning && <details className="reasoning-detail"><summary>查看模型思考内容</summary><pre>{reasoning}</pre></details>}
    </div>}
  </section>;
}
