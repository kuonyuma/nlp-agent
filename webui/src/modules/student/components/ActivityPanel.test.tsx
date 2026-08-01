import { fireEvent, render, screen } from "@testing-library/react";

import { ActivityPanel } from "./ActivityPanel";

describe("ActivityPanel", () => {
  it("does not crash when a replayed activity has an unknown kind", () => {
    render(<ActivityPanel showReasoning={false} running={false} activities={[{
      id: "unknown", kind: "future-tool" as never, label: "未知工具事件", status: "completed", startedAt: "2026-07-19T00:00:00Z", completedAt: "2026-07-19T00:00:02Z",
    }]} />);
    const trigger = screen.getByRole("button", { name: /已处理 2s/ });
    expect(trigger).toBeVisible();
    fireEvent.click(trigger);
    expect(screen.getByText("未知工具事件")).toBeVisible();
  });

  it("uses the full turn duration instead of a completed tool's zero-length event", () => {
    render(<ActivityPanel
      showReasoning={false}
      running={false}
      startedAt="2026-07-19T00:00:00Z"
      completedAt="2026-07-19T00:00:05Z"
      activities={[{ id: "tool", kind: "tool", label: "工具调用完成", status: "completed", startedAt: "2026-07-19T00:00:02Z", completedAt: "2026-07-19T00:00:02Z" }]}
    />);

    expect(screen.getByRole("button", { name: /已处理 5s/ })).toBeVisible();
  });
});
