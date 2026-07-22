import { Check, ChevronDown, ChevronRight, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { CourseTopic, LearningContext } from "@/lib/types";

const levels = [["beginner", "入门"], ["intermediate", "进阶"], ["advanced", "深入"]] as const;
const modes = [["explain", "讲解模式"], ["socratic", "引导模式"], ["practice", "练习模式"], ["review", "复习模式"]] as const;
type Section = "topic" | "level" | "mode";

export function LearningContextBar({ value, onChange, topics = [], unavailableModes = [], onUnavailableMode }: { value: LearningContext; onChange: (value: LearningContext) => void; topics?: CourseTopic[]; unavailableModes?: LearningContext["mode"][]; onUnavailableMode?: (mode: "practice" | "review") => void }) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const selectedTopic = topics.find((topic) => topic.id === value.topic_id);
  const labels = {
    topic: selectedTopic?.name ?? "未选择主题",
    level: levels.find(([key]) => key === value.level)?.[1] ?? value.level,
    mode: modes.find(([key]) => key === value.mode)?.[1] ?? value.mode,
  };
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) {
        setOpen(false);
        setSection(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const choose = (next: Section, key: string) => {
    if (next === "topic") {
      const topic = topics.find((item) => item.id === key);
      onChange({ ...value, topic_id: topic?.id ?? null, topic_name: topic?.name ?? "" });
    } else if (next === "level") {
      onChange({ ...value, level: key as LearningContext["level"] });
    } else {
      if (unavailableModes.includes(key as LearningContext["mode"])) {
        if (key === "practice" || key === "review") onUnavailableMode?.(key);
        return;
      }
      onChange({ ...value, mode: key as LearningContext["mode"] });
    }
    setOpen(false);
    setSection(null);
  };
  const options = section === "topic"
    ? [["", "未选择主题"], ...topics.map((topic) => [topic.id, topic.name] as const)]
    : section === "level" ? levels : modes;
  return <div className="learning-context-menu" ref={ref}>
    <button className="learning-context-menu-trigger" type="button" aria-label="学习设置" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((current) => { if (current) setSection(null); return !current; })}><SlidersHorizontal size={15} /><span className="learning-context-menu-current">{labels.topic}</span><ChevronDown size={14} /></button>
    {open && <div className={section ? "learning-context-menu-panel has-options" : "learning-context-menu-panel"} role="dialog" aria-label="学习设置" onMouseLeave={() => setSection(null)}>
      <div className="learning-context-menu-sections">
        {(["topic", "level", "mode"] as const).map((item) => {
          return <button key={item} type="button" aria-label={item === "topic" ? "学习主题" : item === "level" ? "学习难度" : "教学模式"} className={section === item ? "active" : ""} onMouseEnter={() => setSection(item)} onFocus={() => setSection(item)} onClick={() => setSection(item)}><span>{item === "topic" ? "主题" : item === "level" ? "水平" : "模式"}</span><small>{labels[item]}</small><ChevronRight size={14} /></button>;
          return <button key={item} type="button" aria-label={item === "topic" ? "学习主题" : item === "level" ? "学习难度" : "教学模式"} className={section === item ? "active" : ""} onMouseEnter={() => setSection(item)} onFocus={() => setSection(item)} onClick={() => setSection(item)}><span>{item === "topic" ? "主题" : item === "level" ? "水平" : "模式"}</span><small>{labels[item]}</small><ChevronRight size={14} /></button>;
        })}
      </div>
      {section && <div className="learning-context-menu-options" role="listbox" aria-label={section === "topic" ? "学习主题选项" : section === "level" ? "学习难度选项" : "教学模式选项"}>
        <strong>{section === "topic" ? "选择主题" : section === "level" ? "选择水平" : "选择模式"}</strong>
        {options.map(([key, label]) => {
          const unavailable = section === "mode" && unavailableModes.includes(key as LearningContext["mode"]);
          const selected = section === "topic" ? key === (value.topic_id ?? "") : section === "level" ? key === value.level : key === value.mode;
          return <button key={key} type="button" role="option" aria-selected={selected} aria-disabled={unavailable} className={unavailable ? "unavailable" : ""} onClick={() => choose(section, key)}><span>{label}{unavailable && "（未配置）"}</span>{selected && <Check size={15} />}</button>;
        })}
      </div>}
    </div>}
  </div>;
}
