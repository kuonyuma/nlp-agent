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

  it("switches to the backend cancel action while streaming", () => {
    const onCancel = vi.fn();
    render(<Composer disabled={false} running onSend={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByLabelText("停止生成"));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
