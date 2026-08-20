import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";

import { Sidebar } from "./Sidebar";

const props: ComponentProps<typeof Sidebar> = {
  sessions: [{ session_id: "session_1", user_id: "student", workspace_id: "default", channel: "web" }],
  preferences: { version: 2, context: { topic_id: null, topic_name: "", level: "beginner", mode: "explain" }, categories: [{ id: "category_1", name: "注意力机制", createdAt: 1 }], sessions: { session_1: { title: "Attention 入门", categoryId: "category_1" } } },
  activeId: "session_1", open: true, collapsed: false, connected: true,
  onClose: vi.fn(), onCollapse: vi.fn(), onExpand: vi.fn(), onSelect: vi.fn(), onCreate: vi.fn(), onMeta: vi.fn(), onAddCategory: vi.fn(() => "category_2"), onRenameCategory: vi.fn(), onDeleteCategory: vi.fn(), onDelete: vi.fn(), onAccount: vi.fn(), onSettings: vi.fn(),
};

describe("Sidebar delete requests", () => {
  it("uses the Nova brand mark", () => {
    const { container } = render(<Sidebar {...props} />);

    expect(container.querySelector(".brand-mark img")).toHaveAttribute("src", expect.stringContaining("nova-remove"));
  });

  it("places account management below settings in the sidebar footer", () => {
    const { container } = render(<Sidebar {...props} />);

    const footerButtons = Array.from(container.querySelectorAll(".sidebar-footer .side-action"));
    expect(footerButtons.map((button) => button.getAttribute("aria-label"))).toEqual(["settings", "账户管理"]);
    fireEvent.click(screen.getByRole("button", { name: "账户管理" }));
    expect(props.onAccount).toHaveBeenCalledTimes(1);
  });

  it("delegates session and category deletion to the shared confirmation owner", () => {
    render(<Sidebar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(props.onDelete).toHaveBeenCalledWith("session_1", "Attention 入门");

    fireEvent.click(screen.getByRole("button", { name: "删除分类" }));
    expect(props.onDeleteCategory).toHaveBeenCalledWith("category_1", "注意力机制");
  });

  it("expands when the collapsed rail is clicked", () => {
    const onExpand = vi.fn();
    const { container } = render(<Sidebar {...props} open={false} collapsed onExpand={onExpand} />);

    fireEvent.click(container.querySelector("aside")!);

    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it("keeps the new-chat action usable while the sidebar rail is collapsed", () => {
    const onCreate = vi.fn();
    const onExpand = vi.fn();
    render(<Sidebar {...props} open={false} collapsed onCreate={onCreate} onExpand={onExpand} />);

    fireEvent.click(screen.getByRole("button", { name: "newChat" }));

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onExpand).not.toHaveBeenCalled();
  });

  it("creates a category through the custom dialog without using a native prompt", () => {
    const onAddCategory = vi.fn(() => "category_3");
    render(<Sidebar {...props} onAddCategory={onAddCategory} />);

    fireEvent.click(screen.getByRole("button", { name: "newCategory" }));
    expect(screen.getByRole("dialog", { name: "新建分类" })).toBeVisible();
    expect(screen.getByRole("button", { name: "创建分类" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("分类名称"), { target: { value: "文本分类" } });
    fireEvent.click(screen.getByRole("button", { name: "创建分类" }));

    expect(onAddCategory).toHaveBeenCalledWith("文本分类");
    expect(screen.queryByRole("dialog", { name: "新建分类" })).not.toBeInTheDocument();
  });

  it("closes category creation with Escape without changing categories", () => {
    const onAddCategory = vi.fn();
    render(<Sidebar {...props} onAddCategory={onAddCategory} />);

    fireEvent.click(screen.getByRole("button", { name: "newCategory" }));
    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "新建分类" })).not.toBeInTheDocument();
    expect(onAddCategory).not.toHaveBeenCalled();
  });

  it("renders the backend title when the session has no manual rename", () => {
    const sessions = [{ session_id: "session_2", user_id: "student", workspace_id: "default", channel: "web", title: "Transformer 模型讲解" }];
    render(<Sidebar {...props} sessions={sessions} preferences={{ ...props.preferences, sessions: {} }} />);

    expect(screen.getByText("Transformer 模型讲解")).toBeInTheDocument();
  });

  it("prefers a manual rename over the backend title", () => {
    const sessions = [{ session_id: "session_3", user_id: "student", workspace_id: "default", channel: "web", title: "后端摘要" }];
    render(<Sidebar {...props} sessions={sessions} preferences={{ ...props.preferences, sessions: { session_3: { title: "我的重命名" } } }} />);

    expect(screen.getByText("我的重命名")).toBeInTheDocument();
    expect(screen.queryByText("后端摘要")).not.toBeInTheDocument();
  });
});
