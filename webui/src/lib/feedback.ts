const FEEDBACK_STORAGE_KEY = "nlp-agent.feedback.v1";

export type StoredFeedback = {
  id: string;
  content: string;
  createdAt: string;
};

export function saveFeedback(content: string): StoredFeedback {
  const item: StoredFeedback = {
    id: crypto.randomUUID(),
    content: content.trim(),
    createdAt: new Date().toISOString(),
  };
  const current = loadFeedback();
  localStorage.setItem(FEEDBACK_STORAGE_KEY, JSON.stringify([...current, item].slice(-100)));
  return item;
}

export function loadFeedback(): StoredFeedback[] {
  try {
    const value = JSON.parse(localStorage.getItem(FEEDBACK_STORAGE_KEY) ?? "[]") as unknown;
    return Array.isArray(value) ? value.filter((item): item is StoredFeedback => (
      typeof item === "object" && item !== null && typeof (item as StoredFeedback).content === "string"
    )) : [];
  } catch {
    return [];
  }
}
