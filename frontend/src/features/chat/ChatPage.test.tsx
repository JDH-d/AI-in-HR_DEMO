import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatMessage } from "../../api/types";
import { ChatPage } from "./ChatPage";
import { useChatWorkspace } from "./useChatWorkspace";

vi.mock("./useChatWorkspace", () => ({useChatWorkspace: vi.fn()}));
vi.mock("../../components/Shell", () => ({Shell: ({children}: {children: ReactNode}) => <main>{children}</main>}));
vi.mock("./ConversationControls", () => ({ConversationActions: () => null, ConversationList: () => null, ConversationSearch: () => null}));
vi.mock("../requests/RequestDrawer", () => ({RequestDrawer: () => null}));
vi.mock("../requests/RequestDetailDrawer", () => ({RequestDetailDrawer: () => null}));
vi.mock("../feedback/FeedbackButtons", () => ({FeedbackButtons: () => null}));

let workspace: ReturnType<typeof useChatWorkspace>;
let scrollPosition = 2100;
const scrolledContent: string[] = [];
const scrolledElements: HTMLElement[] = [];
const scrollTo = vi.fn(function(this: HTMLElement) {
  scrolledContent.push(document.body.textContent ?? "");
  scrolledElements.push(this);
});
const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const savedMessages: ChatMessage[] = [
  {id: "question", role: "user", content: "Earlier question", status: "complete"},
  {id: "answer", role: "assistant", content: "Earlier answer", status: "complete"},
];

beforeEach(() => {
  vi.clearAllMocks();
  scrolledContent.length = 0;
  scrolledElements.length = 0;
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {configurable: true, value: scrollTo});
  scrollPosition = 2100;
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(3000);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(900);
  vi.spyOn(HTMLElement.prototype, "scrollTop", "get").mockImplementation(() => scrollPosition);
  workspace = {
    employee: true,
    conversations: {id: "saved", busy: false, pending: false, unavailable: false, messages: savedMessages, draft: "", setDraft: vi.fn(), send: vi.fn(), select: vi.fn(), newConversation: vi.fn(), retryLast: vi.fn(),
      detail: {data: {conversation: {id: "saved", title: "Saved conversation"}, messages: savedMessages}, refetch: vi.fn()}},
    requests: {data: {requests: []}, isSuccess: true},
    drawer: false, setDrawer: vi.fn(), requestDraft: null, selectedRequest: null,
    setSelectedRequest: vi.fn(), openNewRequest: vi.fn(), openRequest: vi.fn(),
  } as unknown as ReturnType<typeof useChatWorkspace>;
  vi.mocked(useChatWorkspace).mockImplementation(() => workspace);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
});

function updateMessages(messages: ChatMessage[]) {
  workspace.conversations = {...workspace.conversations, messages};
}

function scrollToPosition(top: number) {
  scrollPosition = top;
  fireEvent.scroll(screen.getByRole("region", {name: "Conversation messages"}));
}

it("preserves numbered questions on separate lines in saved user messages", () => {
  const content = "1. When is payroll?\n2. Who approves vacation?\n3. How do I request VPN access?";
  updateMessages([{id: "question", role: "user", content, status: "complete"}]);
  render(<ChatPage/>);
  const bubble = screen.getByText(/1\. When is payroll/);
  expect(bubble.textContent).toBe(content);
  expect(bubble).toHaveClass("whitespace-pre-wrap");
});

it("scrolls loaded history inside the message viewport while keeping the composer outside it", () => {
  const loadedDetail = workspace.conversations.detail;
  workspace.conversations.detail = {data: undefined, isLoading: true} as typeof loadedDetail;
  updateMessages([]);
  const {rerender} = render(<ChatPage/>);
  expect(scrollTo).not.toHaveBeenCalled();
  workspace.conversations.detail = loadedDetail;
  updateMessages(savedMessages);
  rerender(<ChatPage/>);
  expect(scrolledContent.at(-1)).toContain("Earlier answer");
  const anchor = scrolledElements.at(-1)!;
  const composer = screen.getByRole("textbox", {name: "Message PeopleFlow AI"});
  expect(anchor).toBe(screen.getByRole("region", {name: "Conversation messages"}));
  expect(anchor).not.toContainElement(composer);
  expect(scrollTo).toHaveBeenCalledWith({behavior: "auto", top: 3000});
});

it("follows committed long replies but stops while the reader scrolls up and resumes near the bottom", () => {
  const {rerender} = render(<ChatPage/>);
  scrollTo.mockClear();
  const answer = "A detailed reply covering each question.\n".repeat(40);
  updateMessages([...savedMessages, {id: "long", role: "assistant", content: answer, status: "complete"}]);
  rerender(<ChatPage/>);
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(scrolledContent.at(-1)).toContain(answer.trimEnd());

  scrollToPosition(900);
  scrollTo.mockClear();
  updateMessages([...workspace.conversations.messages, {id: "later", role: "assistant", content: "More detail", status: "pending"}]);
  rerender(<ChatPage/>);
  expect(scrollTo).not.toHaveBeenCalled();

  scrollToPosition(2050);
  updateMessages(workspace.conversations.messages.map(message => message.id === "later" ? {...message, content: "Final detail", status: "complete"} : message));
  rerender(<ChatPage/>);
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(scrolledContent.at(-1)).toContain("Final detail");
});

it("shows the latest messages when a different saved conversation is selected", () => {
  const {rerender} = render(<ChatPage/>);
  scrollToPosition(900);
  scrollTo.mockClear();
  workspace.conversations = {...workspace.conversations, id: "another"};
  updateMessages([{id: "other", role: "assistant", content: "Another saved answer", status: "complete"}]);
  rerender(<ChatPage/>);
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(scrolledContent.at(-1)).toContain("Another saved answer");
});

it("follows a locally submitted message even when the reader was viewing older messages", () => {
  const {rerender} = render(<ChatPage/>);
  scrollToPosition(900);
  scrollTo.mockClear();
  workspace.conversations = {...workspace.conversations, busy: true, pending: true};
  updateMessages([...savedMessages, {id: "new", role: "user", content: "My follow-up", status: "complete"}]);
  rerender(<ChatPage/>);
  expect(scrollTo).toHaveBeenCalledTimes(1);
  expect(scrolledContent.at(-1)).toContain("My follow-up");
});

it("uses a secondary empty-state heading when the saved conversation already has a page title", () => {
  updateMessages([]);
  const {rerender} = render(<ChatPage/>);
  expect(screen.getByRole("heading", {level: 2, name: "How can we help with work?"})).toBeInTheDocument();
  workspace.conversations = {...workspace.conversations, id: null, detail: {...workspace.conversations.detail, data: undefined}};
  rerender(<ChatPage/>);
  expect(screen.getByRole("heading", {level: 1, name: "How can we help with work?"})).toBeInTheDocument();
});

it("announces answer progress and completion without announcing streaming content", () => {
  workspace.conversations = {...workspace.conversations, busy: true, pending: true};
  updateMessages([...savedMessages, {id: "new-answer", role: "assistant", content: "First token", status: "pending", streaming: true}]);
  const {rerender} = render(<ChatPage/>);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("PeopleFlow is preparing an answer.");
  updateMessages(workspace.conversations.messages.map(message => message.id === "new-answer" ? {...message, content: "The streamed answer grows."} : message));
  rerender(<ChatPage/>);
  expect(status.textContent).toBe("PeopleFlow is preparing an answer.");
  workspace.conversations = {...workspace.conversations, busy: false, pending: false};
  updateMessages(workspace.conversations.messages.map(message => message.id === "new-answer" ? {...message, status: "complete", streaming: false} : message));
  rerender(<ChatPage/>);
  expect(status).toHaveTextContent("Answer ready.");
});

it("never announces an answer as ready after failure or while history is unavailable", () => {
  workspace.conversations = {...workspace.conversations, error: "Unable to send this message.", canRetry: true};
  const {rerender} = render(<ChatPage/>);
  expect(screen.getByRole("alert")).toHaveTextContent("Unable to send this message.");
  expect(screen.getByRole("status")).toBeEmptyDOMElement();

  workspace.conversations = {...workspace.conversations, error: "", canRetry: true};
  updateMessages([...savedMessages, {id: "failed", role: "assistant", content: "", status: "failed"}]);
  rerender(<ChatPage/>);
  expect(screen.getByRole("status")).toHaveTextContent("The answer could not be completed. Use Retry last message.");

  workspace.conversations = {...workspace.conversations, canRetry: false, detail: {...workspace.conversations.detail, isError: true} as typeof workspace.conversations.detail};
  updateMessages(savedMessages);
  rerender(<ChatPage/>);
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});

it("explains chat and request choices without sending anything when an empty conversation opens", () => {
  updateMessages([]);
  render(<ChatPage/>);
  expect(screen.getByText(/Ask in English about company policies/)).toHaveTextContent("For something that needs review or approval, create a request.");
  expect(workspace.conversations.send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Create request"}));
  expect(workspace.openNewRequest).toHaveBeenCalledTimes(1);
  expect(workspace.conversations.send).not.toHaveBeenCalled();
});

it("offers recovery from an inaccessible conversation without creating or deleting a saved chat", () => {
  workspace.conversations = {...workspace.conversations, draft: "Keep this unsent question", messages: [], unavailable: true,
    detail: {...workspace.conversations.detail, data: undefined, isError: true, error: new Error("Conversation unavailable")} as typeof workspace.conversations.detail};
  render(<ChatPage/>);
  expect(screen.getByRole("alert")).toHaveTextContent("This conversation is no longer available to you.");
  expect(screen.queryByRole("heading", {name: "How can we help with work?"})).not.toBeInTheDocument();
  expect(screen.queryByText("New conversation")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", {name: "Message PeopleFlow AI"})).toHaveValue("Keep this unsent question");
  expect(screen.getByRole("button", {name: "Send message"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "Reload conversation"}));
  expect(workspace.conversations.detail.refetch).toHaveBeenCalledTimes(1);
  expect(workspace.conversations.select).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Start a new conversation"}));
  expect(workspace.conversations.select).toHaveBeenCalledWith(null);
  expect(workspace.conversations.newConversation).not.toHaveBeenCalled();
  expect(workspace.conversations.send).not.toHaveBeenCalled();
});

it("keeps cached messages and the draft visible when refreshing history fails", () => {
  workspace.conversations = {...workspace.conversations, draft: "A follow-up", detail: {...workspace.conversations.detail, isError: true, error: new Error("Offline")} as typeof workspace.conversations.detail};
  render(<ChatPage/>);
  expect(screen.getByRole("alert")).toHaveTextContent("Previously loaded messages are shown below.");
  expect(screen.getByText("Earlier answer")).toBeInTheDocument();
  expect(screen.getByRole("textbox", {name: "Message PeopleFlow AI"})).toHaveValue("A follow-up");
  expect(screen.queryByRole("button", {name: "Start a new conversation"})).not.toBeInTheDocument();
  expect(workspace.conversations.setDraft).not.toHaveBeenCalled();
});

it("retries the saved attempt only after an explicit action and preserves the failed draft", () => {
  workspace.conversations = {...workspace.conversations, draft: "My original question", error: "The connection was interrupted.", canRetry: true};
  render(<ChatPage/>);
  expect(screen.getByRole("textbox", {name: "Message PeopleFlow AI"})).toHaveValue("My original question");
  expect(screen.getByText(/Your text is kept below/)).toHaveTextContent("Use Retry last message");
  expect(workspace.conversations.retryLast).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Retry last message"}));
  expect(workspace.conversations.retryLast).toHaveBeenCalledTimes(1);
  expect(workspace.conversations.send).not.toHaveBeenCalled();
  expect(workspace.conversations.setDraft).not.toHaveBeenCalled();
});
