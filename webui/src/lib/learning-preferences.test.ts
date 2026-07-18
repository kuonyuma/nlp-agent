import {
  deriveTitle,
  encodeLearningPrompt,
  extractConcepts,
  stripLearningContext,
} from "./learning-preferences";

describe("learning preference adapter", () => {
  it("keeps educational context invisible in the student transcript", () => {
    const content = encodeLearningPrompt("解释注意力机制", {
      topic: "Transformer",
      level: "beginner",
      mode: "explain",
    });
    expect(content).toContain("nlp-learning-context");
    expect(stripLearningContext(content)).toBe("解释注意力机制");
  });

  it("derives compact titles and concept chips", () => {
    expect(deriveTitle("  什么是 Transformer？  ")).toBe("什么是 Transformer？");
    expect(extractConcepts("**Self-Attention** 使用 `Query`、`Key` 和 `Value`。"))
      .toEqual(["Self-Attention", "Query", "Key", "Value"]);
  });
});
