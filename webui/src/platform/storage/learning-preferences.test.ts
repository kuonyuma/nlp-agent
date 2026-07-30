import {
  DEFAULT_CONTEXT,
  deriveTitle,
  encodeLearningPrompt,
  extractConcepts,
  loadLearningPreferences,
  stripLearningContext,
} from "./learning-preferences";

describe("learning preference adapter", () => {
  it("defaults to no selected topic while retaining beginner explanation settings", () => {
    expect(DEFAULT_CONTEXT).toEqual({
      topic_id: null,
      topic_name: "",
      level: "beginner",
      mode: "explain",
    });
  });

  it("keeps educational context invisible in the student transcript", () => {
    const content = encodeLearningPrompt("解释注意力机制", {
      topic_id: "transformer",
      topic_name: "Transformer",
      level: "beginner",
      mode: "explain",
    });
    expect(content).toContain("nlp-learning-context");
    expect(stripLearningContext(content)).toBe("解释注意力机制");
  });

  it("treats a legacy topic name without a topic ID as unselected", () => {
    localStorage.setItem("nlp-agent.learning-preferences.v1", JSON.stringify({
      version: 2,
      context: { topic_id: null, topic_name: "Transformer", level: "intermediate", mode: "explain" },
      sessions: {},
      categories: [],
    }));

    expect(loadLearningPreferences().context).toEqual({
      topic_id: null,
      topic_name: "",
      level: "intermediate",
      mode: "explain",
    });
  });

  it("does not restore a v1 topic name as an active teacher-managed topic", () => {
    localStorage.setItem("nlp-agent.learning-preferences.v1", JSON.stringify({
      version: 1,
      context: { topic: "Transformer", level: "advanced", mode: "review" },
      sessions: {},
    }));

    expect(loadLearningPreferences().context).toEqual({
      topic_id: null,
      topic_name: "",
      level: "advanced",
      mode: "review",
    });
  });

  it("derives compact titles and concept chips", () => {
    expect(deriveTitle("  什么是 Transformer？  ")).toBe("什么是 Transformer？");
    expect(extractConcepts("**Self-Attention** 使用 `Query`、`Key` 和 `Value`。"))
      .toEqual(["Self-Attention", "Query", "Key", "Value"]);
  });
});
