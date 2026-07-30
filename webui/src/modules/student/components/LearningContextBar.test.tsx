import { fireEvent, render, screen } from "@testing-library/react";

import { LearningContextBar } from "./LearningContextBar";

describe("LearningContextBar", () => {
  it("shows an unselected topic consistently and never falls back to a stale topic name", () => {
    render(<LearningContextBar
      value={{ topic_id: null, topic_name: "Transformer", level: "intermediate", mode: "explain" }}
      onChange={vi.fn()}
      topics={[{ id: "retrieval", name: "TF-IDF 与 FAQ 检索", description: "", status: "enabled", knowledge_points: [] }]}
    />);

    expect(screen.getByRole("button", { name: "学习设置" })).toHaveTextContent("未选择主题");
    fireEvent.click(screen.getByRole("button", { name: "学习设置" }));
    expect(screen.getByRole("button", { name: "学习主题" })).toHaveTextContent("未选择主题");
    expect(screen.queryByText("Transformer")).not.toBeInTheDocument();
  });

  it("lists only teacher-provided topics and selects their stable ID", () => {
    const onChange = vi.fn();
    render(<LearningContextBar
      value={{ topic_id: null, topic_name: "", level: "beginner", mode: "explain" }}
      onChange={onChange}
      topics={[{ id: "retrieval", name: "TF-IDF 与 FAQ 检索", description: "", status: "enabled", knowledge_points: [] }]}
    />);

    fireEvent.click(screen.getByRole("button", { name: "学习设置" }));
    fireEvent.click(screen.getByRole("button", { name: "学习主题" }));
    expect(screen.getByRole("option", { name: "TF-IDF 与 FAQ 检索" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "NLP 基础" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "TF-IDF 与 FAQ 检索" }));

    expect(onChange).toHaveBeenCalledWith({
      topic_id: "retrieval",
      topic_name: "TF-IDF 与 FAQ 检索",
      level: "beginner",
      mode: "explain",
    });
  });

  it("keeps an unavailable practice mode selectable only through its configuration notice", () => {
    const onChange = vi.fn();
    const onUnavailableMode = vi.fn();
    render(<LearningContextBar
      value={{ topic_id: "retrieval", topic_name: "TF-IDF 与 FAQ 检索", level: "beginner", mode: "explain" }}
      onChange={onChange}
      onUnavailableMode={onUnavailableMode}
      unavailableModes={["practice", "review"]}
      topics={[{ id: "retrieval", name: "TF-IDF 与 FAQ 检索", description: "", status: "enabled", knowledge_points: [] }]}
    />);

    fireEvent.click(screen.getByRole("button", { name: "学习设置" }));
    fireEvent.click(screen.getByRole("button", { name: "教学模式" }));
    fireEvent.click(screen.getByRole("option", { name: "练习模式（未配置）" }));

    expect(onUnavailableMode).toHaveBeenCalledWith("practice");
    expect(onChange).not.toHaveBeenCalled();
  });
});
