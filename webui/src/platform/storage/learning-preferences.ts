import type { LearningContext, LearningPreferences, SessionLearningMeta } from "@/shared/types";

const KEY = "nlp-agent.learning-preferences.v1";

export const DEFAULT_CONTEXT: LearningContext = {
  topic_id: null,
  topic_name: "",
  level: "beginner",
  mode: "explain",
};

type StoredLearningContext = Partial<LearningContext> & { topic?: unknown };

/**
 * A topic name is display metadata, not a selection.  Older browser state only
 * stored the name, which left the header and topic picker disagreeing after the
 * teacher-managed catalogue switched to stable topic IDs.
 */
function normalizeLearningContext(raw: unknown): LearningContext {
  const value = raw && typeof raw === "object" ? raw as StoredLearningContext : {};
  const topicId = typeof value.topic_id === "string" && value.topic_id.trim() ? value.topic_id : null;
  const level = value.level === "intermediate" || value.level === "advanced" ? value.level : "beginner";
  const mode = value.mode === "socratic" || value.mode === "practice" || value.mode === "review" ? value.mode : "explain";

  return {
    topic_id: topicId,
    topic_name: topicId && typeof value.topic_name === "string" ? value.topic_name : "",
    level,
    mode,
  };
}

export function loadLearningPreferences(): LearningPreferences {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "null") as {
      version?: number;
      context?: LearningPreferences["context"];
      sessions?: LearningPreferences["sessions"];
      categories?: LearningPreferences["categories"];
    } | null;
    if (value?.version === 2 && value.context && value.sessions) {
      return { version: 2, context: normalizeLearningContext(value.context), sessions: value.sessions, categories: value.categories ?? [] };
    }
    if (value?.version === 1 && value.context && value.sessions) {
      return { version: 2, context: normalizeLearningContext(value.context), sessions: value.sessions, categories: [] };
    }
  } catch {
    // A corrupt browser preference must never block chat startup.
  }
  return { version: 2, context: DEFAULT_CONTEXT, sessions: {}, categories: [] };
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
  const topic = context.topic_name || "未选择";
  return `<!-- nlp-learning-context:${meta} -->\n[学习设置：主题=${topic}；难度=${level}；教学方式=${mode}]\n${content.trim()}`;
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
