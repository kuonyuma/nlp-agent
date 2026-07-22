import { render, screen } from "@testing-library/react";

import { AppErrorBoundary } from "./AppErrorBoundary";
import { MessageList } from "./MessageList";
import type { ChatMessage } from "@/lib/types";

const message = (id: string, content: string): ChatMessage => ({ id, turnId: id, role: "user", content, createdAt: "2026-07-19T00:00:00Z" });
const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;

describe("MessageList session updates", () => {
  afterEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: originalScrollIntoView });
  });

  it("does not treat the browser scrollIntoView return value as an effect cleanup", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn(() => Promise.resolve()) });
    const view = (messages: ChatMessage[]) => <AppErrorBoundary><MessageList messages={messages} loading={false} showReasoning={false} onFollowUp={vi.fn()} /></AppErrorBoundary>;

    const { rerender } = render(view([message("turn-1", "第一个会话")]));
    rerender(view([message("turn-2", "第二个会话")]));

    expect(screen.getByText("第二个会话")).toBeVisible();
    expect(screen.queryByText("页面未能正常显示")).not.toBeInTheDocument();
    consoleError.mockRestore();
  });
});
