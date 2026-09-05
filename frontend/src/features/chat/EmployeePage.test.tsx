import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ChatStreamEvent,
  ConversationSummary,
  Source,
  WorkflowRequest,
} from "../../api/types";
import { ThemeProvider } from "../../app/theme";
import { EmployeePage } from "./EmployeePage";

const { apiMock, streamMock } = vi.hoisted(() => ({ apiMock: vi.fn(), streamMock: vi.fn() }));

vi.mock("../../api/client", () => ({ api: apiMock, streamChat: streamMock }));
vi.mock("../../app/providers", () => ({
  useAuth: () => ({
    token: "employee-token",
    user: { id: "employee.demo", display_name: "Demo Employee", role: "employee" },
    logout: vi.fn(),
  }),
}));

const request: WorkflowRequest = {
  id: "request-1",
  type: "pto",
  type_label: "Vacation / PTO",
  start_date: "2030-04-10",
  end_date: "2030-04-12",
  duration_days: 3,
  comment: "Handoff is ready.",
  applicant: "employee.demo",
  approver: "manager.demo",
  status: "draft",
  details: {},
  created_at: "2030-04-01T09:00:00Z",
  updated_at: "2030-04-01T09:00:00Z",
};
const source: Source = {
  source: "pto-policy.md",
  title: "PTO Policy",
  section: "Planning time off",
  category: "Time off",
  version: "2",
  excerpt: "Request vacation at least ten business days in advance.",
  score: 0.95,
};
const activeStorageKey = "peopleflow.active-conversation.employee.demo";
let conversations: ConversationSummary[];
let requests: WorkflowRequest[];
let deleteFailuresRemaining: number;

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <EmployeePage />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function sendMessage(prompt: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Message PeopleFlow AI" }), {
    target: { value: prompt },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "New Chat" })).toBeEnabled());
}

describe("Employee workspace interactions", () => {
  beforeEach(() => {
    localStorage.clear();
    conversations = [];
    requests = [];
    deleteFailuresRemaining = 0;
    apiMock.mockReset();
    streamMock.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    apiMock.mockImplementation(async (path: string, _token: string, options?: RequestInit) => {
      if (options?.method === "DELETE" && path.startsWith("/api/v1/conversations/")) {
        if (deleteFailuresRemaining > 0) {
          deleteFailuresRemaining -= 1;
          throw new Error("Couldn't delete this chat. Try again.");
        }
        const id = decodeURIComponent(path.slice("/api/v1/conversations/".length));
        conversations = conversations.filter((conversation) => conversation.id !== id);
        return undefined;
      }
      if (path === "/api/v1/conversations") return { conversations };
      if (path === "/api/v1/requests") return { requests };
      throw new Error(`Unexpected API call: ${path}`);
    });
    streamMock.mockImplementation(
      async (
        _token: string,
        prompt: string,
        onEvent: (event: ChatStreamEvent) => void,
        conversationId?: string,
      ) => {
        const id = conversationId ?? `conversation-${conversations.length + 1}`;
        if (!conversations.some((conversation) => conversation.id === id)) {
          conversations = [
            ...conversations,
            {
              id,
              title: prompt,
              message_count: 2,
              created_at: "2030-04-01T09:00:00Z",
              updated_at: "2030-04-01T09:00:00Z",
            },
          ];
        }
        requests = [request];
        onEvent({ type: "start" });
        onEvent({ type: "token", content: "Your time-off draft " });
        await Promise.resolve();
        onEvent({ type: "token", content: "is ready for review." });
        onEvent({
          type: "complete",
          conversation_id: id,
          intent: "pto",
          language: "en",
          outcome_code: "workflow_draft",
          sources: [source],
          workflow_request: request,
        });
      },
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("streams an answer and keeps its source and request available without opening a drawer", async () => {
    renderWorkspace();
    const prompt = "Please draft vacation for April 10–12.";
    await sendMessage(prompt);

    expect(streamMock).toHaveBeenCalledWith(
      "employee-token",
      prompt,
      expect.any(Function),
      undefined,
    );
    const response = await screen.findByRole("article", { name: "PeopleFlow response" });
    expect(screen.getByRole("textbox", { name: "Message PeopleFlow AI" })).toHaveValue("");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const sourceTitle = within(response).getByText(source.title, { selector: "summary span" });
    const disclosure = sourceTitle.closest("details");
    const excerpt = within(response).getByText(source.excerpt);
    expect(disclosure).not.toHaveAttribute("open");
    expect(excerpt).not.toBeVisible();
    fireEvent.click(sourceTitle);
    expect(disclosure).toHaveAttribute("open");
    expect(excerpt).toBeVisible();
    fireEvent.click(sourceTitle);
    expect(excerpt).not.toBeVisible();

    const card = within(response).getByRole("region", { name: "Vacation / PTO request" });
    expect(within(card).getByText("3 calendar days")).toBeInTheDocument();
    expect(within(card).getByText(request.comment)).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Review request" }));

    const drawer = await screen.findByRole("dialog", { name: "Review time off" });
    expect(within(drawer).getByLabelText("First day")).toHaveValue(request.start_date);
    expect(within(drawer).getByLabelText("Last day")).toHaveValue(request.end_date);
    expect(within(drawer).getByLabelText(/Planning note/)).toHaveValue(request.comment);
    expect(apiMock.mock.calls.every(([, , options]) => !options?.method)).toBe(true);
  });

  it("starts a separate conversation while keeping the previous one in history", async () => {
    renderWorkspace();
    const firstPrompt = "Help me plan time off.";
    await sendMessage(firstPrompt);
    const firstHistoryItem = await within(
      screen.getByRole("navigation", { name: "Conversation history" }),
    ).findByRole("button", { name: firstPrompt });
    expect(firstHistoryItem).toHaveAttribute("aria-current", "page");
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-1");

    fireEvent.change(screen.getByRole("textbox", { name: "Message PeopleFlow AI" }), {
      target: { value: "Unsent follow-up" },
    });
    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));

    expect(screen.getByRole("heading", { name: "How can I help?" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "PeopleFlow response" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message PeopleFlow AI" })).toHaveValue("");
    expect(localStorage.getItem(activeStorageKey)).toBeNull();
    expect(firstHistoryItem).toBeInTheDocument();
    expect(firstHistoryItem).not.toHaveAttribute("aria-current");

    await sendMessage("Plan a different absence.");
    expect(streamMock.mock.calls[1][3]).toBeUndefined();
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-2");
  });

  it("changes theme without losing the conversation or unsent message", async () => {
    renderWorkspace();
    await sendMessage("Plan my vacation.");
    const response = screen.getByRole("article", { name: "PeopleFlow response" });
    const draft = "Could I shift it by one day?";
    const composer = screen.getByRole("textbox", { name: "Message PeopleFlow AI" });
    fireEvent.change(composer, { target: { value: draft } });

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("peopleflow.theme")).toBe("light");
    expect(composer).toHaveValue(draft);
    expect(response).toBeInTheDocument();
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-1");

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(composer).toHaveValue(draft);
    expect(streamMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(streamMock).toHaveBeenCalledTimes(2));
    expect(streamMock.mock.calls[1][1]).toBe(draft);
    expect(streamMock.mock.calls[1][3]).toBe("conversation-1");
  });

  it("opens a new request from mobile navigation before dismissing the menu", async () => {
    renderWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const menu = await screen.findByRole("dialog", { name: "Workspace navigation" });

    fireEvent.click(within(menu).getByRole("button", { name: "New request" }));

    const form = await screen.findByRole("dialog", { name: "Plan time off" });
    expect(form).toBeVisible();
    expect(within(form).getByLabelText("Request type")).toHaveValue("pto");
    expect(within(form).getByLabelText("First day")).toHaveValue("");
    expect(screen.queryByRole("dialog", { name: "Workspace navigation" })).not.toBeInTheDocument();
  });

  it("keeps mobile navigation open while expanding requests and restores focus on close", async () => {
    requests = Array.from({ length: 6 }, (_, index) => ({
      ...request,
      id: `request-${index + 1}`,
      type_label: `PTO ${index + 1}`,
    }));
    renderWorkspace();
    const opener = screen.getByRole("button", { name: "Open navigation" });
    opener.focus();
    fireEvent.click(opener);
    const menu = await screen.findByRole("dialog", { name: "Workspace navigation" });
    const viewAll = await within(menu).findByRole("button", { name: "View all 6 requests" });
    expect(within(menu).getAllByRole("button", { name: /^Open PTO \d request/ })).toHaveLength(4);

    fireEvent.click(viewAll);

    expect(menu).toBeVisible();
    expect(within(menu).getAllByRole("button", { name: /^Open PTO \d request/ })).toHaveLength(6);
    expect(within(menu).getByRole("button", { name: "Show less" })).toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("button", { name: "Close navigation" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Workspace navigation" }),
      ).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
    });
  });

  it("cancels without deleting, then deletes the active chat while retaining its requests", async () => {
    renderWorkspace();
    const title = "Plan my vacation.";
    await sendMessage(title);
    const trigger = await screen.findByRole("button", { name: `Delete chat: ${title}` });
    fireEvent.click(trigger);
    let dialog = await screen.findByRole("dialog", { name: "Delete chat?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(apiMock.mock.calls.some(([, , options]) => options?.method === "DELETE")).toBe(false);
    expect(screen.getByRole("article", { name: "PeopleFlow response" })).toBeInTheDocument();
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-1");

    fireEvent.click(trigger);
    dialog = await screen.findByRole("dialog", { name: "Delete chat?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());

    expect(apiMock).toHaveBeenCalledWith("/api/v1/conversations/conversation-1", "employee-token", {
      method: "DELETE",
    });
    expect(screen.getByRole("heading", { name: "New Chat" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "PeopleFlow response" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message PeopleFlow AI" })).toHaveValue("");
    expect(localStorage.getItem(activeStorageKey)).toBeNull();
    expect(screen.queryByRole("button", { name: `Delete chat: ${title}` })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "My requests" })).getByRole("button", {
        name: "Open Vacation / PTO request, status draft",
      }),
    ).toBeInTheDocument();
    expect(requests).toEqual([request]);
  });

  it("deletes a different chat without changing the active conversation or unsent message", async () => {
    renderWorkspace();
    await sendMessage("Old vacation planning.");
    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));
    const activeTitle = "Current vacation planning.";
    await sendMessage(activeTitle);
    const response = screen.getByRole("article", { name: "PeopleFlow response" });
    const composer = screen.getByRole("textbox", { name: "Message PeopleFlow AI" });
    fireEvent.change(composer, { target: { value: "Keep this unsent follow-up." } });

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete chat: Old vacation planning." }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Delete chat?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());

    expect(response).toBeInTheDocument();
    expect(composer).toHaveValue("Keep this unsent follow-up.");
    expect(screen.getByRole("heading", { name: activeTitle })).toBeInTheDocument();
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-2");
    expect(screen.getByRole("button", { name: activeTitle })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(conversations.map((conversation) => conversation.id)).toEqual(["conversation-2"]);
    expect(streamMock).toHaveBeenCalledTimes(2);
  });

  it("keeps a failed deletion open with an error and permits a successful retry", async () => {
    renderWorkspace();
    const title = "A chat to delete.";
    await sendMessage(title);
    deleteFailuresRemaining = 1;
    fireEvent.click(await screen.findByRole("button", { name: `Delete chat: ${title}` }));
    const dialog = await screen.findByRole("dialog", { name: "Delete chat?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Couldn't delete this chat. Try again.",
    );
    expect(dialog).toBeVisible();
    expect(conversations).toHaveLength(1);
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-1");
    expect(within(dialog).getByRole("button", { name: "Delete chat" })).toBeEnabled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Delete chat" }));
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(apiMock.mock.calls.filter(([, , options]) => options?.method === "DELETE")).toHaveLength(
      2,
    );
    expect(conversations).toHaveLength(0);
    expect(localStorage.getItem(activeStorageKey)).toBeNull();
  });

  it("retains mobile navigation and restores its delete button focus after cancellation", async () => {
    renderWorkspace();
    const title = "Mobile chat.";
    await sendMessage(title);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const menu = await screen.findByRole("dialog", { name: "Workspace navigation" });
    const trigger = within(menu).getByRole("button", { name: `Delete chat: ${title}` });
    // jsdom has no layout; represent the visible trigger for the focus-restoration guard.
    vi.spyOn(trigger, "getClientRects").mockReturnValue({ length: 1 } as DOMRectList);
    trigger.focus();
    fireEvent.click(trigger);
    const confirmation = await screen.findByRole("dialog", { name: "Delete chat?" });
    expect(menu).toBeInTheDocument();
    expect(within(confirmation).getByRole("button", { name: "Cancel" })).toHaveFocus();

    fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(confirmation).not.toBeInTheDocument();
      expect(screen.getByRole("dialog", { name: "Workspace navigation" })).toBeVisible();
      expect(trigger).toHaveFocus();
    });
    expect(apiMock.mock.calls.some(([, , options]) => options?.method === "DELETE")).toBe(false);
    expect(localStorage.getItem(activeStorageKey)).toBe("conversation-1");
  });
});
