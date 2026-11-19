import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Link, MemoryRouter, Outlet, RouterProvider } from "react-router";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, streamChat } from "../../api/client";
import type { ConversationDetail } from "../../api/types";
import { useConversations } from "./useConversations";
import { UnsavedChangesProvider } from "../../components/UnsavedChanges";
import { ConversationList, ConversationSearch } from "./ConversationControls";

vi.mock("../../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/client")>(),
  api: vi.fn(), streamChat: vi.fn(),
}));
vi.mock("../../app/providers", () => ({useAuth: () => ({token: "test", user: {id: "employee.demo"}})}));
const stamp = "2030-01-01T12:00:00+00:00";
let saved: ConversationDetail;
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  saved = {conversation: {id: "saved-chat", owner_id: "employee.demo", title: "Vacation", created_at: stamp, updated_at: stamp},
    messages: [{id: "q1", role: "user", content: "Earlier question", turn_id: "old", status: "complete", created_at: stamp},
      {id: "a1", role: "assistant", content: "Earlier reply", turn_id: "old", status: "complete", created_at: stamp}]};
  vi.mocked(api).mockImplementation(async path => path.includes("?")
    ? {conversations: path.includes("missing") ? [] : [saved.conversation], has_more: false}
    : structuredClone(saved));
});

function mount() {
  const cache = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  const wrapper = ({children}: {children: ReactNode}) => <MemoryRouter initialEntries={["/employee?conversation=saved-chat"]}>
    <QueryClientProvider client={cache}>{children}</QueryClientProvider></MemoryRouter>;
  return renderHook(() => {
    const history = useConversations(vi.fn(), vi.fn());
    // Subscribe to error state just as ChatPage does during render.
    void history.detail.isError;
    void history.list.data;
    return history;
  }, {wrapper});
}

it("reloads saved messages after remount and continues with only the new user message", async () => {
  let hook = mount();
  await waitFor(() => expect(hook.result.current.messages).toHaveLength(2));
  hook.unmount();
  hook = mount();
  await waitFor(() => expect(hook.result.current.messages[1].content).toBe("Earlier reply"));
  vi.mocked(streamChat).mockImplementation(async (_token, request, emit) => {
    const user = {id: "q2", role: "user" as const, content: request.content, turn_id: request.requestId, created_at: stamp, status: "complete" as const};
    const answer = {id: "a2", role: "assistant" as const, content: "Continuation", turn_id: request.requestId, created_at: stamp, status: "complete" as const};
    saved.messages.push(user, answer);
    emit({type: "start", user_message: user, conversation: saved.conversation});
    emit({type: "token", content: "Continuation"});
    emit({type: "complete", user_message: user, message: answer, conversation: saved.conversation});
  });
  await act(async () => { await hook.result.current.send("Follow up"); });
  expect(vi.mocked(streamChat).mock.calls[0][1]).toEqual({conversationId: "saved-chat", content: "Follow up", requestId: expect.any(String)});
  await waitFor(() => expect(hook.result.current.messages).toHaveLength(4));
  expect(hook.result.current.messages[3].content).toBe("Continuation");
});

it("recovers the committed reply when the streaming connection breaks", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  vi.mocked(streamChat).mockImplementation(async (_token, request) => {
    saved.messages.push({id: "q2", role: "user", content: request.content, turn_id: request.requestId, status: "complete"},
      {id: "a2", role: "assistant", content: "Saved before disconnect", turn_id: request.requestId, status: "complete"});
    throw new Error("Connection closed");
  });
  await act(async () => { await result.current.send("Follow up"); });
  await waitFor(() => expect(result.current.messages.at(-1)?.content).toBe("Saved before disconnect"));
  expect(result.current.error).toBe("");
  expect(result.current.canRetry).toBe(false);
});

it("retains the same request ID for retry and prevents overlapping sends", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  vi.mocked(streamChat).mockRejectedValue(new Error("Offline"));
  await act(async () => { await Promise.all([result.current.send("One"), result.current.send("Two")]); });
  expect(streamChat).toHaveBeenCalledTimes(1);
  const original = vi.mocked(streamChat).mock.calls[0][1];
  expect(result.current.canRetry).toBe(true);
  act(() => result.current.retryLast());
  await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));
  expect(vi.mocked(streamChat).mock.calls[1][1]).toEqual(original);
  await waitFor(() => expect(result.current.busy).toBe(false));
});

it("restores the typed draft after failure and reuses its request ID through the Send button", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  const typed = "  Follow up with my earlier context  ";
  act(() => result.current.setDraft(typed));
  vi.mocked(streamChat).mockRejectedValueOnce(new Error("Offline"));
  await act(async () => { await result.current.send(); });
  expect(result.current.draft).toBe(typed);
  expect(result.current.error).toBe("Offline");
  const original = vi.mocked(streamChat).mock.calls[0][1];
  vi.mocked(streamChat).mockImplementation(async (_token, request, emit) => {
    const user = {id: "q2", role: "user" as const, content: request.content, turn_id: request.requestId, status: "complete" as const};
    const answer = {id: "a2", role: "assistant" as const, content: "Recovered", turn_id: request.requestId, status: "complete" as const};
    saved.messages.push(user, answer);
    emit({type: "complete", conversation: saved.conversation, user_message: user, message: answer});
  });
  await act(async () => { await result.current.send(); });
  expect(vi.mocked(streamChat).mock.calls[1][1]).toEqual(original);
  expect(result.current.messages).toHaveLength(4);
  expect(result.current.draft).toBe("");
  expect(result.current.error).toBe("");
  expect(result.current.canRetry).toBe(false);
});

it("clears a recovered draft if the server saved the reply before disconnecting", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  act(() => result.current.setDraft("Already saved"));
  vi.mocked(streamChat).mockImplementation(async (_token, request) => {
    saved.messages.push({id: "q2", role: "user", content: request.content, turn_id: request.requestId, status: "complete"},
      {id: "a2", role: "assistant", content: "Saved reply", turn_id: request.requestId, status: "complete"});
    throw new Error("Connection closed");
  });
  await act(async () => { await result.current.send(); });
  expect(result.current.messages).toHaveLength(4);
  expect(result.current.draft).toBe("");
  expect(result.current.error).toBe("");
  expect(result.current.canRetry).toBe(false);
});

it("allows retry with cached history when the recovery request also fails", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.detail.isSuccess).toBe(true));
  act(() => result.current.setDraft("Keep this question"));
  vi.mocked(streamChat).mockRejectedValue(new Error("Offline"));
  vi.mocked(api).mockRejectedValue(new ApiError(503, "Unavailable"));
  await act(async () => { await result.current.send(); });
  await waitFor(() => expect(result.current.detail.isError).toBe(true));
  expect(result.current.draft).toBe("Keep this question");
  expect(result.current.messages).toEqual(saved.messages);
  const original = vi.mocked(streamChat).mock.calls[0][1];
  await act(async () => { await result.current.send(); });
  expect(streamChat).toHaveBeenCalledTimes(2);
  expect(vi.mocked(streamChat).mock.calls[1][1]).toEqual(original);
  expect(result.current.draft).toBe("Keep this question");
});

it("searches server-side history and handles no matches", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
  act(() => result.current.setSearch("missing"));
  await waitFor(() => expect(result.current.list.data?.pages[0].conversations).toEqual([]));
  expect(api).toHaveBeenCalledWith(expect.stringContaining("q=missing"), "test", expect.anything());
});

function SearchableHistory() {
  const history = useConversations(vi.fn(), vi.fn());
  return <><ConversationSearch history={history} onShowHistory={() => {}}/><ConversationList history={history}/></>;
}

function mountSearchableHistory() {
  const cache = new QueryClient({defaultOptions: {queries: {retry: false}}});
  render(<MemoryRouter initialEntries={["/employee"]}><QueryClientProvider client={cache}><SearchableHistory/></QueryClientProvider></MemoryRouter>);
}

it("hides the previous results while a newly typed search is being debounced", async () => {
  mountSearchableHistory();
  await screen.findByRole("button", {name: /^Vacation/});
  fireEvent.change(screen.getByRole("searchbox", {name: "Search history"}), {target: {value: "missing"}});
  expect(screen.getByRole("status")).toHaveTextContent("Searching conversations…");
  expect(screen.getByRole("region", {name: "Your conversations"})).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByRole("button", {name: /^Vacation/})).not.toBeInTheDocument();
  expect(screen.queryByText(/No conversations match/)).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("q=missing"))).toBe(false);
  expect(await screen.findByText(/No conversations match/)).toBeInTheDocument();
  expect(screen.getByRole("region", {name: "Your conversations"})).toHaveAttribute("aria-busy", "false");
});

it("clears a no-match search without briefly claiming the saved history is empty", async () => {
  mountSearchableHistory();
  await screen.findByRole("button", {name: /^Vacation/});
  fireEvent.change(screen.getByRole("searchbox", {name: "Search history"}), {target: {value: "missing"}});
  await screen.findByText(/No conversations match/);
  fireEvent.click(screen.getByRole("button", {name: "Clear search"}));
  expect(screen.getByRole("searchbox", {name: "Search history"})).toHaveValue("");
  expect(screen.getByRole("heading", {name: "Recent conversations"})).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent("Loading conversations…");
  expect(screen.queryByText(/No conversations yet/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No conversations match/)).not.toBeInTheDocument();
  expect(await screen.findByRole("button", {name: /^Vacation/})).toBeInTheDocument();
  expect(screen.queryByText(/No conversations yet/)).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.every(([, , options]) => !options?.method)).toBe(true);
});

it.each([403, 404])("hides cached messages when a previously open conversation becomes unavailable (%s)", async status => {
  const {result} = mount();
  await waitFor(() => expect(result.current.messages).toHaveLength(2));
  expect(result.current.unavailable).toBe(false);
  vi.mocked(api).mockImplementation(async path => {
    if (!path.includes("?")) throw new ApiError(status, "Conversation not found.");
    return {conversations: [], has_more: false};
  });
  await act(async () => { await result.current.detail.refetch(); });
  await waitFor(() => expect(result.current.detail.isError).toBe(true));
  expect(result.current.unavailable).toBe(true);
  expect(result.current.messages).toEqual([]);
  expect(result.current.detail.data).toBeUndefined();
  await waitFor(() => expect(result.current.list.data?.pages[0].conversations).toEqual([]));
});

it("keeps saved messages visible during a temporary server error", async () => {
  const {result} = mount();
  await waitFor(() => expect(result.current.messages).toHaveLength(2));
  vi.mocked(api).mockRejectedValue(new ApiError(503, "Service temporarily unavailable"));
  await act(async () => { await result.current.detail.refetch(); });
  await waitFor(() => expect(result.current.detail.isError).toBe(true));
  expect(result.current.unavailable).toBe(false);
  expect(result.current.messages).toEqual(saved.messages);
  expect(result.current.detail.data?.conversation.id).toBe("saved-chat");
});

function ProtectedChat() {
  const history = useConversations(vi.fn(), vi.fn());
  return <>
    <output aria-label="Open conversation">{history.id ?? "New chat"}</output>
    <textarea aria-label="Unsent message" value={history.draft} onChange={event => history.setDraft(event.target.value)}/>
    <button onClick={() => history.select("saved-chat")}>Select current chat</button>
    <button onClick={() => history.select("other-chat")}>Select another chat</button>
    <button onClick={() => void history.newConversation()}>Start new chat</button>
    <button disabled={history.pending || Boolean(history.id && !history.detail.data)} onClick={() => void history.send()}>Send draft</button>
    <button onClick={() => void history.send("Suggested question")}>Use suggested question</button>
    <Link to="/requests">Open requests</Link>
    {history.error && <p role="alert">{history.error}</p>}
    {history.canRetry && <p>Retry is available</p>}
  </>;
}
function protectedMount(entry = "/employee?conversation=saved-chat") {
  const router = createMemoryRouter([{path:"/", element:<UnsavedChangesProvider><Outlet/></UnsavedChangesProvider>, children:[
    {path:"employee", element:<ProtectedChat/>},
    {path:"requests", element:<p>Requests destination</p>},
  ]}], {initialEntries:[entry]});
  const cache = new QueryClient({defaultOptions:{queries:{retry:false}, mutations:{retry:false}}});
  render(<QueryClientProvider client={cache}><RouterProvider router={router}/></QueryClientProvider>);
  return router;
}

it("preserves a draft when switching chats is cancelled and confirms only once when accepted", async () => {
  protectedMount();
  await waitFor(() => expect(screen.getByRole("button", {name:"Send draft"})).toBeEnabled());
  fireEvent.change(screen.getByRole("textbox", {name:"Unsent message"}), {target:{value:"Keep this unsent text"}});
  fireEvent.click(screen.getByRole("button", {name:"Select current chat"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("Keep this unsent text");
  fireEvent.click(screen.getByRole("button", {name:"Select another chat"}));
  fireEvent.click(await screen.findByRole("button", {name:"Keep editing"}));
  expect(screen.getByLabelText("Open conversation")).toHaveTextContent("saved-chat");
  expect(screen.getByRole("textbox")).toHaveValue("Keep this unsent text");
  fireEvent.click(screen.getByRole("button", {name:"Select another chat"}));
  fireEvent.click(await screen.findByRole("button", {name:"Discard changes and leave"}));
  await waitFor(() => expect(screen.getByLabelText("Open conversation")).toHaveTextContent("other-chat"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(api).not.toHaveBeenCalledWith(expect.anything(), expect.anything(), expect.objectContaining({method:"POST"}));
});

it("does not create a new conversation until discarding the current draft is confirmed", async () => {
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method === "POST") return {conversation:{...saved.conversation, id:"created-chat"}} as never;
    return path.includes("?") ? {conversations:[saved.conversation], has_more:false} as never : structuredClone(saved);
  });
  protectedMount();
  fireEvent.change(screen.getByRole("textbox"), {target:{value:"Do not discard yet"}});
  fireEvent.click(screen.getByRole("button", {name:"Start new chat"}));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", {name:"Keep editing"}));
  expect(screen.getByRole("textbox")).toHaveValue("Do not discard yet");
  fireEvent.click(screen.getByRole("button", {name:"Start new chat"}));
  fireEvent.click(await screen.findByRole("button", {name:"Discard changes and leave"}));
  await waitFor(() => expect(screen.getByLabelText("Open conversation")).toHaveTextContent("created-chat"));
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST")).toHaveLength(1);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("");
});

it("protects an unsent draft from page navigation and tab closing", async () => {
  protectedMount();
  fireEvent.change(screen.getByRole("textbox"), {target:{value:"Unsent message"}});
  const closing = new Event("beforeunload", {cancelable:true});
  window.dispatchEvent(closing);
  expect(closing.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("link", {name:"Open requests"}));
  fireEvent.click(await screen.findByRole("button", {name:"Keep editing"}));
  expect(screen.getByRole("textbox")).toHaveValue("Unsent message");
  fireEvent.click(screen.getByRole("link", {name:"Open requests"}));
  fireEvent.click(await screen.findByRole("button", {name:"Discard changes and leave"}));
  expect(await screen.findByText("Requests destination")).toBeInTheDocument();
});

it("restores draft protection after a failed send", async () => {
  vi.mocked(streamChat).mockRejectedValue(new Error("Offline"));
  protectedMount();
  await waitFor(() => expect(screen.getByRole("button", {name:"Send draft"})).toBeEnabled());
  fireEvent.change(screen.getByRole("textbox"), {target:{value:"Retry this question"}});
  fireEvent.click(screen.getByRole("button", {name:"Send draft"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  await screen.findByText("Retry is available");
  fireEvent.click(screen.getByRole("link", {name:"Open requests"}));
  fireEvent.click(await screen.findByRole("button", {name:"Keep editing"}));
  expect(screen.getByRole("textbox")).toHaveValue("Retry this question");
});

it("keeps the recovered text after a fast failed first send creates the conversation", async () => {
  const created = {...saved.conversation, id:"created-chat"};
  vi.mocked(api).mockImplementation(async (path, _token, options) => options?.method === "POST" ? {conversation:created} as never : path.includes("?") ? {conversations:[created], has_more:false} as never : {conversation:created, messages:[]} as never);
  vi.mocked(streamChat).mockRejectedValue(new Error("Offline"));
  protectedMount("/employee");
  fireEvent.change(screen.getByRole("textbox"), {target:{value:"First message to keep"}});
  fireEvent.click(screen.getByRole("button", {name:"Send draft"}));
  await screen.findByText("Retry is available");
  // Router navigation commits separately from the recovered send state.
  // Check the draft after that transition, when the conversation effect ran.
  await waitFor(() => {
    expect(screen.getByLabelText("Open conversation")).toHaveTextContent("created-chat");
    expect(screen.getByRole("textbox")).toHaveValue("First message to keep");
  });
  const original = vi.mocked(streamChat).mock.calls[0][1];
  fireEvent.click(screen.getByRole("link", {name:"Open requests"}));
  fireEvent.click(await screen.findByRole("button", {name:"Keep editing"}));
  fireEvent.click(screen.getByRole("button", {name:"Send draft"}));
  await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));
  expect(vi.mocked(streamChat).mock.calls[1][1]).toEqual(original);
});

it("does not replace an existing draft with a suggested question without confirmation", async () => {
  vi.mocked(streamChat).mockResolvedValue(undefined);
  protectedMount();
  await waitFor(() => expect(screen.getByRole("button", {name:"Send draft"})).toBeEnabled());
  fireEvent.change(screen.getByRole("textbox"), {target:{value:"My own question"}});
  fireEvent.click(screen.getByRole("button", {name:"Use suggested question"}));
  fireEvent.click(await screen.findByRole("button", {name:"Keep editing"}));
  expect(streamChat).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox")).toHaveValue("My own question");
  fireEvent.click(screen.getByRole("button", {name:"Use suggested question"}));
  fireEvent.click(await screen.findByRole("button", {name:"Discard changes and leave"}));
  await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(1));
  expect(vi.mocked(streamChat).mock.calls[0][1].content).toBe("Suggested question");
});
