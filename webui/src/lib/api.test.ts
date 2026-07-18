import { api, ensureAuth } from "./api";

describe("FastAPI client", () => {
  it("establishes same-origin auth and attaches CSRF to mutations", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ title: "unauthorized" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        user_id: "local",
        workspace_ids: ["default"],
        csrf_token: "csrf-token",
        expires_at: 123,
      }), { status: 201, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ session_id: "session_1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }));

    await ensureAuth();
    await api.createSession();

    const mutation = fetchMock.mock.calls[2][1];
    expect(new Headers(mutation?.headers).get("X-CSRF-Token")).toBe("csrf-token");
    expect(mutation?.credentials).toBe("include");
    fetchMock.mockRestore();
  });
});
