import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProfileDialog } from "./ProfileDialog";

const methods = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getQuota: vi.fn(),
  getUsage: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({ api: methods, ApiError: class ApiError extends Error {} }));
vi.mock("@/platform/auth/AuthContext", () => ({
  useAuth: () => ({ user: { workspace_ids: ["workspace-a", "workspace-b"] } }),
}));
vi.mock("@/platform/realtime/client", () => ({
  StudentSocket: class { connect() {} close() {} },
}));

describe("ProfileDialog quota section", () => {
  beforeEach(() => {
    methods.getCurrentUser.mockResolvedValue({
      id: "user-1", username: "nova", display_name: "Nova", roles: ["student"],
      status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    });
    methods.getQuota.mockResolvedValue({ quota: { user_id: "user-1", workspace_id: "workspace-a", buckets: [] }, policy: null });
    methods.getUsage.mockResolvedValue({ events: 0, priced_credits_micro: 0, unpriced_events: 0, credits_complete: true, tokens: {}, breakdown: [] });
  });

  it("shows personal quota inside settings and scopes requests to an authorized workspace", async () => {
    render(<ProfileDialog open onClose={vi.fn()} sessionRoles={["student"]} />);

    fireEvent.click(await screen.findByRole("button", { name: "额度与用量" }));

    await waitFor(() => expect(methods.getQuota).toHaveBeenCalledWith("workspace-a"));
    expect(methods.getUsage).toHaveBeenCalledWith(30, "workspace-a");
    expect(screen.getByRole("heading", { name: "额度与用量" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "工作空间" })).toHaveValue("workspace-a");
  });

  it("switches the quota scope without leaving the settings dialog", async () => {
    render(<ProfileDialog open onClose={vi.fn()} sessionRoles={["student"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "额度与用量" }));

    fireEvent.change(await screen.findByRole("combobox", { name: "工作空间" }), { target: { value: "workspace-b" } });

    await waitFor(() => expect(methods.getQuota).toHaveBeenCalledWith("workspace-b"));
    expect(window.location.pathname).not.toBe("/usage");
  });
});
