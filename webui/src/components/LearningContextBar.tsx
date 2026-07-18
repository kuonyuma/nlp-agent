import { BookOpen, ChevronDown, Gauge, SlidersHorizontal, Sparkles } from "lucide-react";

import type { LearningContext } from "@/lib/types";

const topics = ["NLP 基础", "文本分类", "词向量与表示学习", "Transformer", "大语言模型"];
const levels = [["beginner", "入门"], ["intermediate", "进阶"], ["advanced", "深入"]] as const;
const modes = [["explain", "讲解模式"], ["socratic", "引导模式"], ["practice", "练习模式"], ["review", "复习模式"]] as const;

export function LearningContextBar({ value, onChange }: { value: LearningContext; onChange: (value: LearningContext) => void }) {
  return <div className="learning-context-dock">
    <button className="learning-context-trigger" type="button"><SlidersHorizontal size={14} /><span>{value.topic}</span><ChevronDown size={13} /></button>
    <div className="learning-context-bar">
      <label><BookOpen size={14} /><select aria-label="学习主题" value={value.topic} onChange={(event) => onChange({ ...value, topic: event.target.value })}>{topics.map((topic) => <option key={topic}>{topic}</option>)}</select><ChevronDown size={13} /></label>
      <label><Gauge size={14} /><select aria-label="学习难度" value={value.level} onChange={(event) => onChange({ ...value, level: event.target.value as LearningContext["level"] })}>{levels.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><ChevronDown size={13} /></label>
      <label><Sparkles size={14} /><select aria-label="教学模式" value={value.mode} onChange={(event) => onChange({ ...value, mode: event.target.value as LearningContext["mode"] })}>{modes.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><ChevronDown size={13} /></label>
    </div>
  </div>;
}
