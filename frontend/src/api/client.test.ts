import { afterEach, describe, expect, it, vi } from "vitest";
import { api, streamChat } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("HTTP boundary", () => {
  it("shows FastAPI validation messages instead of object placeholders", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ detail: [{ msg: "Comment is required" }] }),
            { status: 422 },
          ),
        ),
    );
    await expect(api("/api/v1/requests")).rejects.toThrow(
      "Comment is required",
    );
  });

  it("preserves split UTF-8, whitespace and the final event without a newline", async () => {
    const text = "Line one\n  Привет\n";
    const bytes = new TextEncoder().encode(
      JSON.stringify({ type: "token", content: text }) +
        '\n{"type":"complete"}',
    );
    const body = new ReadableStream({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    const events: Record<string, unknown>[] = [];
    await streamChat("token", {conversationId: "chat-1", content: "Hello", requestId: "turn-1"}, (event) => events.push(event));
    expect(events).toEqual([
      { type: "token", content: text },
      { type: "complete" },
    ]);
  });

  it("reports a truncated response instead of leaving the chat waiting", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"type":"start"}\n')),
    );
    await expect(streamChat("token", {conversationId: "chat-1", content: "Hello", requestId: "turn-1"}, () => {})).rejects.toThrow(
      "interrupted",
    );
  });
});
