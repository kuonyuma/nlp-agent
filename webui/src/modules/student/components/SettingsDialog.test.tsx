import { fireEvent, render, screen } from "@testing-library/react";

import { SettingsDialog } from "./SettingsDialog";
import { loadFeedback } from "@/shared/utils/feedback";
import type { UserSettings } from "@/shared/types";

const settings: UserSettings = {
  theme: "system",
  locale: "zh-CN",
  show_reasoning: true,
  stream_render_interval_ms: 30,
  default_workspace_id: "default",
};

describe("SettingsDialog", () => {
  beforeEach(() => localStorage.clear());

  it("persists submitted feedback before reporting success", () => {
    render(<SettingsDialog
      open
      settings={settings}
      learningContext={{ topic_id: null, topic_name: "", level: "beginner", mode: "explain" }}
      onClose={() => {}}
      onChange={() => {}}
      onLearningContextChange={() => {}}
      onOpenDeveloper={() => {}}
      onOpenTeacher={() => {}}
    />);
    fireEvent.click(screen.getByRole("button", { name: "意见反馈" }));
    fireEvent.change(screen.getByPlaceholderText(/我希望/), { target: { value: "请增加错题计划" } });
    fireEvent.click(screen.getByRole("button", { name: "发布意见" }));

    expect(loadFeedback().map((item) => item.content)).toEqual(["请增加错题计划"]);
    expect(screen.getByText("已将本次意见保存在此浏览器。")).toBeVisible();
  });
});
