import { act, renderHook, waitFor } from "@testing-library/react";

import { useStudentWorkspace } from "./useStudentWorkspace";
import { api } from "@/platform/http/api";

const { ensureAuthMock, getSettingsMock, createSessionMock } = vi.hoisted(() => ({
  ensureAuthMock: vi.fn(),
  getSettingsMock: vi.fn(),
  createSessionMock: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({
  ensureAuth: ensureAuthMock,
  api: {
    listSessions: vi.fn(async () => ({ items: [] })),
    getSettings: getSettingsMock,
    createSession: createSessionMock,
    updateSettings: vi.fn(),
  },
}));

vi.mock("@/platform/realtime/client", () => ({
  StudentSocket: class {
    connect() {}
    close() {}
    setSession() {}
  },
}));

describe("useStudentWorkspace settings", () => {
  let dark = false;
  let onChange: (() => void) | undefined;

  beforeEach(() => {
    localStorage.clear();
    dark = false;
    onChange = undefined;
    document.documentElement.classList.remove("dark");
    ensureAuthMock.mockResolvedValue({ csrf_token: "x", workspace_ids: ["default"] });
    getSettingsMock.mockResolvedValue({ preferences: { settings: { theme: "system" } } });
    createSessionMock.mockResolvedValue({ session_id: "session-new", user_id: "user", workspace_id: "default", channel: "web" });
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      get matches() { return dark; },
      addEventListener: (_type: string, listener: () => void) => { onChange = listener; },
      removeEventListener: vi.fn(),
    })));
    vi.mocked(api.updateSettings).mockReset();
    vi.mocked(api.listSessions).mockResolvedValue({ items: [] });
  });

  it("rolls back optimistic settings and exposes a visible error on network failure", async () => {
    vi.mocked(api.updateSettings).mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useStudentWorkspace());
    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));

    await act(async () => { await result.current.patchSettings({ theme: "dark" }); });

    expect(result.current.settings.theme).toBe("system");
    expect(result.current.settingsError).toContain("offline");
  });

  it("rolls consecutive failed writes back to the last confirmed settings", async () => {
    vi.mocked(api.updateSettings)
      .mockRejectedValueOnce(new Error("first failed"))
      .mockRejectedValueOnce(new Error("second failed"));
    const { result } = renderHook(() => useStudentWorkspace());
    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));

    await act(async () => {
      await Promise.all([
        result.current.patchSettings({ theme: "dark" }),
        result.current.patchSettings({ locale: "en-US" }),
      ]);
    });

    expect(result.current.settings.theme).toBe("system");
    expect(result.current.settings.locale).toBe("zh-CN");
    expect(result.current.settingsError).toContain("second failed");
  });

  it("clears an earlier failure after a later queued setting is saved", async () => {
    vi.mocked(api.updateSettings)
      .mockRejectedValueOnce(new Error("first failed"))
      .mockResolvedValueOnce({ settings: {
        theme: "light", locale: "zh-CN", show_reasoning: true,
        stream_render_interval_ms: 30, default_workspace_id: "default",
      } });
    const { result } = renderHook(() => useStudentWorkspace());
    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));

    await act(async () => {
      await Promise.all([
        result.current.patchSettings({ theme: "dark" }),
        result.current.patchSettings({ theme: "light" }),
      ]);
    });

    expect(result.current.settings.theme).toBe("light");
    expect(result.current.settingsError).toBe("");
  });

  it("tracks operating-system theme changes while using system mode", async () => {
    const { result } = renderHook(() => useStudentWorkspace());
    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));
    expect(document.documentElement).not.toHaveClass("dark");

    dark = true;
    act(() => onChange?.());

    expect(document.documentElement).toHaveClass("dark");
  });

  it("removes browser-side metadata for sessions deleted by a monitor reset", async () => {
    localStorage.setItem("nlp-agent.learning-preferences.v1", JSON.stringify({
      version: 2,
      context: { topic_id: null, topic_name: "", level: "beginner", mode: "explain" },
      categories: [],
      sessions: { "deleted-session": { title: "旧对话", updatedAt: 1 } },
    }));
    const { result } = renderHook(() => useStudentWorkspace());

    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));

    expect(result.current.preferences.sessions).toEqual({});
    expect(JSON.parse(localStorage.getItem("nlp-agent.learning-preferences.v1") ?? "{}").sessions).toEqual({});
  });

  it("creates new sessions in the authorized default workspace from user settings", async () => {
    ensureAuthMock.mockResolvedValue({ csrf_token: "x", workspace_ids: ["default", "research"] });
    getSettingsMock.mockResolvedValue({ preferences: { settings: { theme: "system", default_workspace_id: "research" } } });
    createSessionMock.mockResolvedValue({ session_id: "session-research", user_id: "user", workspace_id: "research", channel: "web" });
    const { result } = renderHook(() => useStudentWorkspace());
    await waitFor(() => expect(result.current.bootStatus).toBe("ready"));

    await act(async () => { await result.current.createSession(); });

    expect(result.current.workspaceId).toBe("research");
    expect(createSessionMock).toHaveBeenCalledWith("research");
  });
});
