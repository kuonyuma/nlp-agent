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

  it("sends preset questions directly instead of stacking them into the input", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running={false} onSend={onSend} onCancel={vi.fn()} />);
    const input = screen.getByLabelText("学习问题");
    fireEvent.change(input, { target: { value: "前一个问题" } });
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).toHaveBeenCalledWith("用简单语言解释");
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  it("does not send preset questions while a turn is running", () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} running onSend={onSend} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "用简单语言解释" }));

    expect(onSend).not.toHaveBeenCalled();
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
});
