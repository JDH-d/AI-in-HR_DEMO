import { afterEach, describe, expect, it, vi } from "vitest";
import { api, parseStoredUser, streamChat } from "./client";
import type { ChatStreamEvent } from "./types";

function streamedResponse(...chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

describe("streamChat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses NDJSON when an event is split across transport chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          streamedResponse(
            '{"type":"start"}\n{"type":"tok',
            'en","content":"Hello"}\n',
            '{"type":"complete","intent":"work","language":"en","outcome_code":"grounded","sources":[],',
            '"workflow_request":null,"conversation_id":"conversation-1"}\n',
          ),
        ),
    );
    const events: ChatStreamEvent[] = [];

    await streamChat("token", "Hello", (event) => events.push(event));

    expect(events).toEqual([
      { type: "start" },
      { type: "token", content: "Hello" },
      {
        type: "complete",
        intent: "work",
        language: "en",
        outcome_code: "grounded",
        sources: [],
        workflow_request: null,
        conversation_id: "conversation-1",
      },
    ]);
  });

  it("rejects a stream that closes without a terminal event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamedResponse('{"type":"token","content":"partial"}\n')),
    );

    await expect(streamChat("token", "Hello", () => undefined)).rejects.toEqual(
      expect.objectContaining({ status: 502 }),
    );
  });

  it("surfaces an HTTP error returned before streaming starts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Authentication token has expired." }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(streamChat("expired", "Hello", () => undefined)).rejects.toEqual(
      expect.objectContaining({
        status: 401,
        message: "Authentication token has expired.",
      }),
    );
  });
});

describe("parseStoredUser", () => {
  it("accepts only a complete known demo identity", () => {
    expect(
      parseStoredUser(
        JSON.stringify({
          id: "employee.demo",
          username: "employee",
          display_name: "Demo Employee",
          role: "employee",
          manager_id: "manager.demo",
        }),
      ),
    ).toEqual({
      id: "employee.demo",
      username: "employee",
      display_name: "Demo Employee",
      role: "employee",
      manager_id: "manager.demo",
    });
    expect(parseStoredUser('{"role":"owner"}')).toBeNull();
    expect(parseStoredUser("not-json")).toBeNull();
  });
});

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts an empty successful DELETE response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      api<void>("/api/v1/conversations/chat-1", "token", { method: "DELETE" }),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/chat-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("surfaces FastAPI validation messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { type: "string_too_short", loc: ["body", "comment"], msg: "Comment is required" },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(api("/api/v1/requests", "token")).rejects.toEqual(
      expect.objectContaining({ status: 422, message: "Comment is required" }),
    );
  });
});
