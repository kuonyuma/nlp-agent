import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

configure({ asyncUtilTimeout: 10000 });
beforeEach(() => {
  history.replaceState({}, "", "/");
});
