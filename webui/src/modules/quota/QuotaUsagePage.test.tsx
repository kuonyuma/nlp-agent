import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { QuotaUsagePage } from "./QuotaUsagePage";

const { getQuota, getUsage } = vi.hoisted(() => ({
  getQuota: vi.fn(),
  getUsage: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({
  api: {
    getQuota,
    getUsage,
  },
}));

vi.mock("@/platform/auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      user_id: "user-1",
      workspace_ids: ["workspace-a", "workspace-b"],
    },
  }),
}));

vi.mock("@/platform/realtime/client", () => ({
  StudentSocket: class {
    connect() {}
    close() {}
  },
}));

describe("QuotaUsagePage", () => {
  beforeEach(() => {
    getQuota.mockResolvedValue({
      quota: {
        user_id: "user-1",
        workspace_id: "workspace-a",
        buckets: [
          { owner_type: "user", owner_id: "user-1", bucket_type: "daily", limit_micro: 100, grant_micro: 0, adjustment_micro: 0, consumed_micro: 0, reserved_micro: 20, remaining_micro: 80, reset_at: "2026-08-31T00:00:00+00:00", over_limit: false },
          { owner_type: "user", owner_id: "user-1", bucket_type: "monthly", limit_micro: 500, grant_micro: 0, adjustment_micro: 0, consumed_micro: 0, reserved_micro: 300, remaining_micro: 200, reset_at: "2026-09-01T00:00:00+00:00", over_limit: false },
          { owner_type: "workspace", owner_id: "workspace-a", bucket_type: "daily", limit_micro: 120, grant_micro: 0, adjustment_micro: 0, consumed_micro: 0, reserved_micro: 90, remaining_micro: 30, reset_at: "2026-08-31T00:00:00+00:00", over_limit: false },
        ],
      },
      policy: null,
    });
    getUsage.mockResolvedValue({
      events: 0,
      priced_credits_micro: 0,
      breakdown: [
        { day: "2026-08-30", purpose: "coordinator", provider: "openai", provider_model: "gpt-5", events: 2, priced_events: 2, unpriced_events: 0, priced_credits_micro: 42, total_tokens: 120 },
      ],
    });
  });

  it("shows the minimum effective remaining balance instead of summing buckets", async () => {
    render(<QuotaUsagePage />);

    await waitFor(() => expect(screen.getAllByText("30 μcredits").length).toBeGreaterThan(0));
    expect(screen.queryByText("310 μcredits")).not.toBeInTheDocument();
  });

  it("loads the selected workspace for users with multiple workspaces", async () => {
    render(<QuotaUsagePage />);

    const selector = await screen.findByLabelText("工作空间");
    expect(getQuota).toHaveBeenCalledWith("workspace-a");
    expect(getUsage).toHaveBeenCalledWith(30, "workspace-a");
    fireEvent.change(selector, { target: { value: "workspace-b" } });

    await waitFor(() => expect(getQuota).toHaveBeenCalledWith("workspace-b"));
    expect(getUsage).toHaveBeenCalledWith(30, "workspace-b");
  });

  it("shows a workspace-scoped usage breakdown with its accounting status", async () => {
    render(<QuotaUsagePage />);

    expect(await screen.findByText("调用明细")).toBeInTheDocument();
    expect(screen.getByText("coordinator · openai / gpt-5")).toBeInTheDocument();
    expect(screen.getByText("42 μcredits")).toBeInTheDocument();
  });
});
