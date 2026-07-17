import { render, screen } from "@testing-library/react";

import { App } from "./App";

describe("App", () => {
  it("renders the configured WebUI shell", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "WebUI environment is ready" })).toBeVisible();
  });
});
