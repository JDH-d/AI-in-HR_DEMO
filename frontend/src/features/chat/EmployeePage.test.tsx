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
      { name: /My parental leave options/i },
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
});
