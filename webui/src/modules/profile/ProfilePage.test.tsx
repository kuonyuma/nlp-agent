import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProfilePage } from "./ProfilePage";

const methods = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getQuota: vi.fn(),
  getUsage: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({ api: methods, ApiError: class ApiError extends Error {} }));
vi.mock("@/platform/auth/AuthContext", () => ({ useOptionalAuth: () => ({ user: { workspace_ids: ["workspace-a", "workspace-b"] } }) }));

describe("ProfilePage", () => {
  beforeEach(() => {
    methods.getCurrentUser.mockResolvedValue({
      id: "user-1", username: "nova", display_name: "Nova", roles: ["student"],
      status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    });
    methods.getQuota.mockResolvedValue({ quota: { user_id: "user-1", workspace_id: null, buckets: [] }, policy: null });
    methods.getUsage.mockResolvedValue({ events: 0, priced_credits_micro: 0, breakdown: [] });
  });

  it("provides quota as a first-class personal settings section", async () => {
    render(<ProfilePage />);

    fireEvent.click(await screen.findByRole("button", { name: "额度与用量" }));
    await waitFor(() => expect(methods.getQuota).toHaveBeenCalled());
    expect(methods.getQuota).toHaveBeenCalledWith("workspace-a");
    expect(methods.getUsage).toHaveBeenCalledWith(30, "workspace-a");
    expect(screen.getByText("额度与用量概览")).toBeInTheDocument();
  });

  it("allows the compact settings view to switch workspace scope", async () => {
    render(<ProfilePage />);

    fireEvent.click(await screen.findByRole("button", { name: "额度与用量" }));
    const selector = await screen.findByRole("combobox", { name: "工作空间" });
    fireEvent.change(selector, { target: { value: "workspace-b" } });

    await waitFor(() => expect(methods.getQuota).toHaveBeenCalledWith("workspace-b"));
    expect(methods.getUsage).toHaveBeenCalledWith(30, "workspace-b");
  });
});
