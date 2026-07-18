import type { LearningContext, LearningPreferences, SessionLearningMeta } from "./types";

const KEY = "nlp-agent.learning-preferences.v1";

export const DEFAULT_CONTEXT: LearningContext = {
  topic: "NLP 基础",
  level: "beginner",
  mode: "explain",
};

export function loadLearningPreferences(): LearningPreferences {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "null") as LearningPreferences | null;
    if (value?.version === 1) return value;
  } catch {
    // A corrupt browser preference must never block chat startup.
  }
  return { version: 1, context: DEFAULT_CONTEXT, sessions: {} };
}

export function saveLearningPreferences(value: LearningPreferences): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    // Private browsing or storage quotas must not disable the learning chat.
  }
}

export function deriveTitle(input: string): string {
  const clean = stripLearningContext(input).replace(/\s+/g, " ").trim();
  return clean.length > 28 ? `${clean.slice(0, 28)}…` : clean || "新的学习对话";
}

export function encodeLearningPrompt(content: string, context: LearningContext): string {
  const meta = JSON.stringify(context).replace(/-->/g, "--\\>");
  const level = { beginner: "入门", intermediate: "进阶", advanced: "深入" }[context.level];
  const mode = { explain: "讲解", socratic: "苏格拉底式引导", practice: "练习", review: "复习" }[context.mode];
  return `<!-- nlp-learning-context:${meta} -->\n[学习设置：主题=${context.topic}；难度=${level}；教学方式=${mode}]\n${content.trim()}`;
}

export function stripLearningContext(content: string): string {
  return content
    .replace(/^<!-- nlp-learning-context:.*? -->\s*/s, "")
    .replace(/^\[学习设置：.*?]\s*/, "")
    .trim();
}

export function extractConcepts(text: string): string[] {
  const candidates = Array.from(text.matchAll(/(?:\*\*|`)([\w\u4e00-\u9fff][\w\u4e00-\u9fff -]{1,30})(?:\*\*|`)/g))
    .map((match) => match[1].trim())
    .filter((item) => item.length < 24);
  return [...new Set(candidates)].slice(0, 12);
}

export function mergeSessionMeta(
  current: SessionLearningMeta | undefined,
  patch: Partial<SessionLearningMeta>,
): SessionLearningMeta {
  return { ...current, ...patch, updatedAt: Date.now() };
}
