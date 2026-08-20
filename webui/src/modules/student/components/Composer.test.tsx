import { fireEvent, render, screen } from "@testing-library/react";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("submits on Enter and keeps Shift+Enter for multiline questions", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running={false} onSend={onSend} onCancel={vi.fn()} />);
    const input = screen.getByLabelText("学习问题");
    fireEvent.change(input, { target: { value: "解释 BERT" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });
    expect(onSend).toHaveBeenCalledWith("解释 BERT");
  });

  it("sends preset questions through the same send path, preserving typed content", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running={false} onSend={onSend} onCancel={vi.fn()} />);
    const input = screen.getByLabelText("学习问题");
    fireEvent.change(input, { target: { value: "前一个问题" } });
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).toHaveBeenCalledWith("前一个问题\n用简单语言解释");
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  it("sends an empty preset untouched when no content is typed", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running={false} onSend={onSend} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).toHaveBeenCalledWith("用简单语言解释");
  });

  it("trims surrounding whitespace from the merged preset value", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running={false} onSend={onSend} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("学习问题"), { target: { value: "  前一个问题  " } });
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).toHaveBeenCalledWith("前一个问题\n用简单语言解释");
  });

  it("disables preset buttons while a turn is running", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running onSend={onSend} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "用简单语言解释" })).toBeDisabled();
  });

  it("switches to the backend cancel action while streaming", () => {
    const onCancel = vi.fn();
    render(<Composer disabled={false} running onSend={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByLabelText("停止生成"));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("offers available backend models and disables selection while running", () => {
    const onModelProfileChange = vi.fn();
    const props = {
      disabled: false,
      onSend: vi.fn(),
      onCancel: vi.fn(),
      modelProfiles: {
        deepseek: { label: "DeepSeek", provider: "deepseek", available: true },
        qwen: { label: "Qwen", provider: "dashscope", available: true },
        offline: { label: "Offline", provider: "local", available: false },
      },
      modelProfile: "deepseek",
      onModelProfileChange,
    };
    const { rerender } = render(<Composer {...props} running={false} />);
    const select = screen.getByRole("combobox", { name: "选择模型" });

    expect(screen.getByRole("option", { name: "Qwen" })).toBeEnabled();
    expect(screen.getByRole("option", { name: "Offline（不可用）" })).toBeDisabled();
    fireEvent.change(select, { target: { value: "qwen" } });
    expect(onModelProfileChange).toHaveBeenCalledWith("qwen");

    rerender(<Composer {...props} modelProfile="qwen" running />);
    expect(screen.getByRole("combobox", { name: "选择模型" })).toBeDisabled();
  });

  it("renders attachment upload button when sessionId is provided and disables when absent", () => {
    const { rerender } = render(
      <Composer disabled={false} running={false} onSend={vi.fn()} onCancel={vi.fn()} sessionId={null} />
    );
    expect(screen.getByRole("button", { name: "上传附件" })).toBeDisabled();

    rerender(
      <Composer disabled={false} running={false} onSend={vi.fn()} onCancel={vi.fn()} sessionId="sess-1" />
    );
    expect(screen.getByRole("button", { name: "上传附件" })).toBeEnabled();
  });
});
