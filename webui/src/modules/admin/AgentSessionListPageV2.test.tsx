import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AgentSessionListPageV2 } from "./AgentSessionListPageV2";

const { listSessionsMock, getSessionStatsMock, listTurnsMock, renameSessionMock, deleteSessionMock } = vi.hoisted(() => ({
  listSessionsMock: vi.fn(),
  getSessionStatsMock: vi.fn(),
  listTurnsMock: vi.fn(),
  renameSessionMock: vi.fn(),
  deleteSessionMock: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({
  api: {
    listSessions: listSessionsMock,
    getSessionStats: getSessionStatsMock,
    listTurns: listTurnsMock,
    renameSession: renameSessionMock,
    deleteSession: deleteSessionMock,
  },
}));

const session = {
  session_id: "session-abcdef123456",
  title: "排查模型超时",
  title_is_manual: true,
  user_id: "developer-1",
  workspace_id: "default",
  channel: "web",
  created_at: "2026-08-31T08:00:00Z",
  last_active: "2026-08-31T08:30:00Z",
};

describe("AgentSessionListPageV2", () => {
  beforeEach(() => {
    listSessionsMock.mockReset();
    getSessionStatsMock.mockReset();
    listTurnsMock.mockReset();
    renameSessionMock.mockReset();
    deleteSessionMock.mockReset();
    listSessionsMock.mockResolvedValue({ items: [session], total: 25, offset: 0, limit: 24, has_more: true });
    getSessionStatsMock.mockResolvedValue({ sessions_total: 25, sessions_active: 18, turns_total: 72, turns_last_24h: 9, last_activity_at: session.last_active });
    listTurnsMock.mockResolvedValue({ items: [] });
    renameSessionMock.mockResolvedValue({ session_id: session.session_id, title: "新的排查标题" });
    deleteSessionMock.mockResolvedValue(undefined);
  });

  it("explains what sessions are for and keeps the identifier secondary to the title", async () => {
    render(<AgentSessionListPageV2 />);
    expect((await screen.findAllByText("排查模型超时")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/用于回看 Agent 的请求、Turn 状态和运行上下文/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Session ID · session-abcdef/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "排查模型超时" })).toBeVisible();
  });

  it("loads another session page only after the developer asks for more", async () => {
    listSessionsMock
      .mockResolvedValueOnce({ items: [session], total: 25, offset: 0, limit: 24, has_more: true })
      .mockResolvedValueOnce({ items: [{ ...session, session_id: "session-next", title: "验证工具调用" }], total: 25, offset: 24, limit: 24, has_more: false });

    render(<AgentSessionListPageV2 />);
    await screen.findAllByText("排查模型超时");

    expect(screen.getByRole("button", { name: "加载更多会话" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "加载更多会话" }));

    await waitFor(() => expect(listSessionsMock).toHaveBeenLastCalledWith({ limit: 24, offset: 24 }));
    expect(await screen.findByText("验证工具调用")).toBeVisible();
  });

  it("renames a session from its management actions", async () => {
    render(<AgentSessionListPageV2 />);
    await screen.findAllByText("排查模型超时");

    fireEvent.click(screen.getByRole("button", { name: "管理会话 排查模型超时" }));
    fireEvent.click(screen.getByRole("button", { name: "修改名称" }));
    fireEvent.change(screen.getByRole("textbox", { name: "会话名称" }), { target: { value: "新的排查标题" } });
    fireEvent.click(screen.getByRole("button", { name: "保存名称" }));

    await waitFor(() => expect(renameSessionMock).toHaveBeenCalledWith(session.session_id, "新的排查标题"));
  });

  it("loads turns only after selecting a session", async () => {
    render(<AgentSessionListPageV2 />);
    await screen.findAllByText("排查模型超时");

    expect(listTurnsMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "查看会话 排查模型超时" }));

    await waitFor(() => expect(listTurnsMock).toHaveBeenCalledWith(session.session_id));
  });
});
