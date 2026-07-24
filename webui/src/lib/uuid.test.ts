import { createUuid } from "./uuid";

describe("createUuid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses getRandomValues when randomUUID is unavailable in an HTTP context", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0);
        return bytes;
      },
    });

    expect(createUuid()).toBe("00000000-0000-4000-8000-000000000000");
  });

  it("prefers the platform randomUUID implementation when available", () => {
    const randomUUID = vi.fn(() => "platform-uuid");
    vi.stubGlobal("crypto", { randomUUID });

    expect(createUuid()).toBe("platform-uuid");
    expect(randomUUID).toHaveBeenCalledOnce();
  });
});
