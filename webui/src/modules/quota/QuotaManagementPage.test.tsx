import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { QuotaManagementPage } from "./QuotaManagementPage";

const methods = vi.hoisted(() => ({
  listQuotaPolicies: vi.fn(),
  listQuotaBindings: vi.fn(),
  listQuotaGrants: vi.fn(),
  listQuotaAdjustments: vi.fn(),
  listQuotaBilling: vi.fn(),
  listQuotaAlerts: vi.fn(),
  listQuotaDailyRollups: vi.fn(),
  createQuotaPolicy: vi.fn(),
}));

vi.mock("@/platform/http/api", () => ({ api: methods }));

describe("QuotaManagementPage", () => {
  beforeEach(() => {
    Object.values(methods).forEach((method) => method.mockReset());
    methods.listQuotaPolicies.mockResolvedValue({ items: [] });
    methods.listQuotaBindings.mockResolvedValue({ items: [] });
    methods.listQuotaGrants.mockResolvedValue({ items: [] });
    methods.listQuotaAdjustments.mockResolvedValue({ items: [] });
    methods.listQuotaBilling.mockResolvedValue({ items: [] });
    methods.listQuotaAlerts.mockResolvedValue({ items: [] });
    methods.listQuotaDailyRollups.mockResolvedValue({ items: [] });
    methods.createQuotaPolicy.mockResolvedValue({});
  });

  it("loads operational data and exposes gift/reset, reconciliation, alerts and recovery", async () => {
    render(<QuotaManagementPage />);

    await waitFor(() => expect(methods.listQuotaBilling).toHaveBeenCalled());
    expect(methods.listQuotaAlerts).toHaveBeenCalled();
    expect(methods.listQuotaDailyRollups).toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "运营与对账" }));
    expect(screen.getByText("赠送 / 重置 Credits")).toBeInTheDocument();
    expect(screen.getByText("Provider 账单对账")).toBeInTheDocument();
    expect(screen.getByText("告警中心")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "恢复与归档" }));
    expect(screen.getByText("Ledger 重放与 UsageEvent 归档")).toBeInTheDocument();
  });

  it("keeps overdraft and model profile restrictions configurable", async () => {
    render(<QuotaManagementPage />);

    await waitFor(() => expect(methods.listQuotaPolicies).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("版本"), { target: { value: "2026.08.30" } });
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "学生策略" } });
    fireEvent.change(screen.getByLabelText("有限透支"), { target: { value: "5000" } });
    fireEvent.change(screen.getByLabelText("允许模型 Profile"), { target: { value: "economy, premium" } });
    fireEvent.click(screen.getByRole("button", { name: "创建策略草稿" }));

    await waitFor(() => expect(methods.createQuotaPolicy).toHaveBeenCalledWith(expect.objectContaining({
      max_overdraft_micro: 5000,
      allowed_model_profiles: ["economy", "premium"],
      unlimited: false,
    })));
  });
});
