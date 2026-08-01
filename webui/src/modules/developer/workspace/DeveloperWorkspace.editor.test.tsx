import { fireEvent, render, screen } from "@testing-library/react";

import { JsonEditor } from "./DeveloperWorkspace";

describe("JsonEditor", () => {
  it("refreshes its text when a newer snapshot arrives", () => {
    const onSave = vi.fn(async () => {});
    const { rerender } = render(<JsonEditor value={{ revision: 1 }} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: '{"revision":0}' } });

    rerender(<JsonEditor value={{ revision: 2 }} onSave={onSave} />);

    expect(screen.getByRole("textbox")).toHaveValue(JSON.stringify({ revision: 2 }, null, 2));
  });

  it("does not resurrect an old dirty draft when snapshots change A to B to A", () => {
    const onSave = vi.fn(async () => {});
    const { rerender } = render(<JsonEditor value={{ revision: "A" }} onSave={onSave} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: '{"stale":true}' } });
    rerender(<JsonEditor value={{ revision: "B" }} onSave={onSave} />);
    rerender(<JsonEditor value={{ revision: "A" }} onSave={onSave} />);

    expect(screen.getByRole("textbox")).toHaveValue(JSON.stringify({ revision: "A" }, null, 2));
  });
});
