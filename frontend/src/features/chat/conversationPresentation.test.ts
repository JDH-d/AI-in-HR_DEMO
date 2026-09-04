import { describe, expect, it } from "vitest";
import type { ChatMessage, ConversationSummary } from "../../api/types";
import { conversationMeta, restoreConversationMessages } from "./conversationPresentation";

describe("conversation presentation", () => {
  it("restores the employee question associated with each assistant answer", () => {
    const messages: ChatMessage[] = [
      { id: "u1", role: "user", content: "When is payroll processed?" },
      { id: "a1", role: "assistant", content: "Twice each month." },
      { id: "u2", role: "user", content: "What about a holiday?" },
      { id: "a2", role: "assistant", content: "It moves to the prior business day." },
    ];

    const restored = restoreConversationMessages(messages);

    expect(restored[1].question).toBe("When is payroll processed?");
    expect(restored[3].question).toBe("What about a holiday?");
  });

  it("describes persisted history in exchanges rather than raw messages", () => {
    const conversation: ConversationSummary = {
      id: "conversation-1",
      title: "Payroll timing",
      message_count: 4,
      created_at: "2030-04-01T09:00:00Z",
      updated_at: "2030-04-01T10:00:00Z",
    };

    expect(conversationMeta(conversation, new Date("2030-04-02T10:00:00Z"))).toMatch(
      /^2 exchanges · /,
    );
  });
});
