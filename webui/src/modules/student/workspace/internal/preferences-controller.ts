import { useCallback, useRef, useState } from "react";

import {
  loadLearningPreferences,
  mergeSessionMeta,
  saveLearningPreferences,
} from "@/platform/storage/learning-preferences";
import type {
  LearningCategory,
  LearningContext,
  LearningPreferences,
  SessionLearningMeta,
} from "@/shared/types";
import { createUuid } from "@/shared/utils/uuid";

export function usePreferencesController() {
  const [preferences, setPreferences] = useState<LearningPreferences>(() => loadLearningPreferences());
  const preferencesRef = useRef(preferences);

  const persistPreferences = useCallback((update: (current: LearningPreferences) => LearningPreferences) => {
    setPreferences((current) => {
      const next = update(current);
      preferencesRef.current = next;
      saveLearningPreferences(next);
      return next;
    });
  }, []);

  const updateSessionMeta = useCallback((sessionId: string, patch: Partial<SessionLearningMeta>) => {
    persistPreferences((current) => ({
      ...current,
      sessions: {
        ...current.sessions,
        [sessionId]: mergeSessionMeta(current.sessions[sessionId], patch),
      },
    }));
  }, [persistPreferences]);

  const setLearningContext = useCallback((context: LearningContext) => {
    persistPreferences((current) => ({ ...current, context }));
  }, [persistPreferences]);

  const addCategory = useCallback((name: string) => {
    const category: LearningCategory = { id: createUuid(), name: name.trim(), createdAt: Date.now() };
    persistPreferences((current) => ({ ...current, categories: [...current.categories, category] }));
    return category.id;
  }, [persistPreferences]);

  const renameCategory = useCallback((categoryId: string, name: string) => {
    persistPreferences((current) => ({
      ...current,
      categories: current.categories.map((category) => category.id === categoryId ? { ...category, name: name.trim() } : category),
    }));
  }, [persistPreferences]);

  const deleteCategory = useCallback((categoryId: string) => {
    persistPreferences((current) => {
      const sessions = Object.fromEntries(Object.entries(current.sessions).map(([sessionId, meta]) => [
        sessionId,
        meta.categoryId === categoryId ? { ...meta, categoryId: undefined, updatedAt: Date.now() } : meta,
      ]));
      return { ...current, categories: current.categories.filter((category) => category.id !== categoryId), sessions };
    });
  }, [persistPreferences]);

  return {
    preferences,
    preferencesRef,
    persistPreferences,
    updateSessionMeta,
    setLearningContext,
    addCategory,
    renameCategory,
    deleteCategory,
  };
}
