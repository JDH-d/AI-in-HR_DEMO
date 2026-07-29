import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, streamChat } from "../../api/client";
import type { ConversationDetail, ConversationSummary } from "../../api/types";
import { EmployeePage } from "./EmployeePage";

vi.mock("../../api/client", () => ({
  api: vi.fn(),
  streamChat: vi.fn(),
}));
vi.mock("../../app/providers", () => ({
  useAuth: () => ({
    token: "employee-token",
    user: {
      id: "employee.demo",
      username: "employee",
      display_name: "Demo Employee",
      role: "employee",
    },
    logout: vi.fn(),
  }),
}));

const savedConversation: ConversationSummary = {
  id: "conversation-1",
  title: "My parental leave options",
  created_at: "2030-04-01T09:00:00Z",
  updated_at: "2030-04-01T09:01:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EmployeePage />
    </QueryClientProvider>,
  );
}

describe("Employee conversation history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(streamChat).mockResolvedValue(undefined);
    vi.mocked(api).mockImplementation(async path => {
      if (path === "/api/v1/requests") return { requests: [] };
      if (path === "/api/v1/conversations") {
        return { conversations: [savedConversation] };
      }
      if (path === "/api/v1/conversations/conversation-1") {
        return {
          conversation: savedConversation,
          messages: [
            {
              id: "message-1",
              role: "user",
              content: "What parental leave can I take?",
              sources: [],
              created_at: "2030-04-01T09:00:00Z",
            },
            {
              id: "message-2",
              role: "assistant",
              content: "Your saved policy answer.",
              sources: [{
                source: "Leave.md",
                title: "Parental Leave",
                section: "Eligibility",
                category: "leave",
                version: "1.0",
                excerpt: "Employees may take parental leave.",
                score: 0.9,
              }],
              workflow_request: null,
              created_at: "2030-04-01T09:01:00Z",
            },
          ],
        } satisfies ConversationDetail;
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
  });
  afterEach(cleanup);

  it("shows real conversations and restores all saved messages", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole(
      "button",
      { name: "Open conversation My parental leave options" },
      { timeout: 5_000 },
    ));

    expect(await screen.findByText("What parental leave can I take?")).toBeInTheDocument();
    expect(screen.getByText("Your saved policy answer.")).toBeInTheDocument();
    expect(screen.getByText("Sources · 1")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Message PeopleFlow AI"), {
      target: { value: "What documents are needed?" },
    });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => {
      expect(streamChat).toHaveBeenCalledWith(
        "employee-token",
        [
          { role: "user", content: "What parental leave can I take?" },
          { role: "assistant", content: "Your saved policy answer." },
          { role: "user", content: "What documents are needed?" },
        ],
        expect.any(Function),
        "conversation-1",
      );
    });
  });

  it("creates a conversation before sending the first message", async () => {
    vi.mocked(api).mockImplementation(async (path, _token, init) => {
      if (path === "/api/v1/requests") return { requests: [] };
      if (path === "/api/v1/conversations" && init?.method === "POST") {
        return { conversation: { ...savedConversation, id: "conversation-new" } };
      }
      if (path === "/api/v1/conversations") return { conversations: [] };
      throw new Error(`Unexpected API call: ${path}`);
    });
    vi.mocked(streamChat).mockImplementation(async (_token, _messages, onEvent) => {
      onEvent({ type: "token", content: "Saved answer." });
      onEvent({ type: "complete", sources: [], workflow_request: null });
    });
    renderPage();

    fireEvent.change(screen.getByLabelText("Message PeopleFlow AI"), {
      target: { value: "How does leave work?" },
    });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => {
      expect(streamChat).toHaveBeenCalledWith(
        "employee-token",
        [{ role: "user", content: "How does leave work?" }],
        expect.any(Function),
        "conversation-new",
      );
    });
    expect(await screen.findByText("Saved answer.")).toBeInTheDocument();
  });

  it("keeps requests close by while recent conversations expand and collapse", async () => {
    const conversationList = [
      savedConversation,
      ...Array.from({ length: 4 }, (_, index) => ({
        ...savedConversation,
        id: `conversation-${index + 2}`,
        title: `Conversation ${index + 2}`,
      })),
    ];
    vi.mocked(api).mockImplementation(async path => {
      if (path === "/api/v1/requests") return { requests: [] };
      if (path === "/api/v1/conversations") {
        return { conversations: conversationList };
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
    renderPage();

    expect(await screen.findByText("Conversation 3")).toBeInTheDocument();
    expect(screen.queryByText("Conversation 4")).not.toBeInTheDocument();
    expect(screen.getByText("My requests")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all (5)" }));
    expect(await screen.findByText("Conversation 5")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: "Collapse recent conversations",
    }));
    expect(screen.queryByText("My parental leave options")).not.toBeInTheDocument();
    expect(screen.getByText("My requests")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: "Expand recent conversations",
    }));
    expect(await screen.findByText("Conversation 3")).toBeInTheDocument();
    expect(screen.queryByText("Conversation 4")).not.toBeInTheDocument();
  });

  it("confirms deletion and resets an active conversation", async () => {
    vi.mocked(api).mockImplementation(async (path, _token, init) => {
      if (path === "/api/v1/requests") return { requests: [] };
      if (path === "/api/v1/conversations") {
        return { conversations: [savedConversation] };
      }
      if (path === "/api/v1/conversations/conversation-1" && init?.method === "DELETE") {
        return { deleted: true, conversation: savedConversation };
      }
      if (path === "/api/v1/conversations/conversation-1") {
        return {
          conversation: savedConversation,
          messages: [
            {
              id: "message-1",
              role: "user",
              content: "Delete this question.",
              sources: [],
              created_at: "2030-04-01T09:00:00Z",
            },
            {
              id: "message-2",
              role: "assistant",
              content: "Delete this answer.",
              sources: [],
              workflow_request: null,
              created_at: "2030-04-01T09:01:00Z",
            },
          ],
        } satisfies ConversationDetail;
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", {
      name: "Open conversation My parental leave options",
    }));
    expect(await screen.findByText("Delete this answer.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: "Delete conversation My parental leave options",
    }));
    expect(screen.getByRole("heading", { name: "Delete conversation?" })).toBeInTheDocument();
    expect(screen.getByText(
      "This permanently removes the conversation and all of its messages.",
    )).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete conversation" }));

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/conversations/conversation-1",
        "employee-token",
        { method: "DELETE" },
      );
    });
    expect(await screen.findByText(
      "Good morning. I can answer policy questions with evidence, or turn a clear action into a request you review before sending.",
    )).toBeInTheDocument();
    expect(screen.queryByText("Delete this answer.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {
      name: "Delete conversation My parental leave options",
    })).not.toBeInTheDocument();
  });
});
