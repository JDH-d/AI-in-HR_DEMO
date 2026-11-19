import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { ConversationActions, ConversationList, ConversationSearch } from "./ConversationControls";
import type { useConversations } from "./useConversations";

afterEach(cleanup);
function setup() {
  const remove = vi.fn().mockResolvedValue(undefined);
  const rename = vi.fn().mockResolvedValue(undefined);
  const history = {id: "chat", pending: false, detail: {data: {conversation: {title: "Saved chat"}}}, remove, rename} as unknown as ReturnType<typeof useConversations>;
  render(<ConversationActions history={history}/>);
  return {remove, rename};
}
function chooseAction(name: "Rename conversation" | "Delete conversation") {
  fireEvent.click(screen.getByRole("button", {name: "Conversation actions"}));
  expect(screen.getByRole("dialog", {name: "Conversation actions"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name}));
}

it("requires explicit confirmation before deleting and allows cancellation", async () => {
  const {remove} = setup();
  expect(screen.getByRole("heading", {level:1, name:"Saved chat"})).toBeInTheDocument();
  chooseAction("Delete conversation");
  expect(screen.getByRole("dialog", {name: "Delete conversation?"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "Cancel"})).toHaveFocus();
  expect(screen.getByRole("dialog")).toHaveTextContent("Unsent text in this chat is also discarded");
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
  expect(remove).not.toHaveBeenCalled();
  chooseAction("Delete conversation");
  fireEvent.click(screen.getByRole("button", {name: "Delete permanently"}));
  await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("keeps the confirmation open with a clear error if deletion fails", async () => {
  const {remove} = setup();
  remove.mockRejectedValue(new Error("The server is unavailable"));
  chooseAction("Delete conversation");
  fireEvent.click(screen.getByRole("button", {name: "Delete permanently"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("The server is unavailable");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

it("rejects blank titles and saves an edited name", async () => {
  const {rename} = setup();
  chooseAction("Rename conversation");
  const title = screen.getByRole("textbox", {name: "Conversation title"});
  fireEvent.change(title, {target: {value: "   "}});
  expect(screen.getByRole("button", {name: "Save name"})).toBeDisabled();
  fireEvent.change(title, {target: {value: "Планы отпуска"}});
  fireEvent.click(screen.getByRole("button", {name: "Save name"}));
  await waitFor(() => expect(rename).toHaveBeenCalledWith("Планы отпуска"));
});

it("saves a renamed conversation with Enter without accepting composition input", async () => {
  const {rename} = setup();
  chooseAction("Rename conversation");
  const title = screen.getByRole("textbox", {name: "Conversation title"});
  fireEvent.change(title, {target: {value: "Vacation plans"}});
  fireEvent.keyDown(title, {key: "Enter", isComposing: true});
  expect(rename).not.toHaveBeenCalled();
  fireEvent.keyDown(title, {key: "Enter"});
  await waitFor(() => expect(rename).toHaveBeenCalledWith("Vacation plans"));
});

it("provides one scoped search and a route to its mobile history results", () => {
  const setSearch = vi.fn();
  const show = vi.fn();
  const history = {search: "Vacation", setSearch} as unknown as ReturnType<typeof useConversations>;
  render(<ConversationSearch history={history} onShowHistory={show}/>);
  const search = screen.getByRole("searchbox", {name: "Search history"});
  expect(search).toHaveAccessibleName("Search history");
  const clear = screen.getByRole("button", {name: "Clear history search"});
  expect(clear.closest("label")).toBeNull();
  fireEvent.change(search, {target: {value: "Payroll"}});
  expect(setSearch).toHaveBeenCalledWith("Payroll");
  fireEvent.click(screen.getByRole("button", {name: "Show conversation history"}));
  expect(show).toHaveBeenCalledTimes(1);
  clear.focus();
  fireEvent.click(clear);
  expect(setSearch).toHaveBeenLastCalledWith("");
  expect(search).toHaveFocus();
});

it("recovers from empty history search without creating a conversation and retains keyboard focus", () => {
  const newConversation = vi.fn();
  function HistoryResults() {
    const [search, setSearch] = useState("Missing policy");
    const history = {search, setSearch, newConversation, list: {isSuccess: true, data: {pages: [{conversations: []}]}}} as unknown as ReturnType<typeof useConversations>;
    return <ConversationList history={history}/>;
  }
  render(<HistoryResults/>);
  expect(screen.getByRole("status")).toHaveTextContent("Change your query or clear the search");
  const clear = screen.getByRole("button", {name: "Clear search"});
  clear.focus();
  fireEvent.click(clear);
  expect(screen.getByRole("heading", {name: "Recent conversations"})).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent("No conversations yet. Send a message to start one.");
  expect(screen.queryByRole("button", {name: "Clear search"})).not.toBeInTheDocument();
  expect(newConversation).not.toHaveBeenCalled();
});

it("does not expose the previous search error, rows or pagination while the query changes", () => {
  const history = {search: "New query", searchPending: true, list: {isError: true, hasNextPage: true, data: {pages: [{conversations: [{id: "old", title: "Previous match", updated_at: "2030-01-01"}]}]}}} as unknown as ReturnType<typeof useConversations>;
  render(<ConversationList history={history}/>);
  expect(screen.getByRole("status")).toHaveTextContent("Searching conversations…");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: /Previous match/})).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Load more conversations"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Retry history"})).not.toBeInTheDocument();
});

it("dismisses conversation actions with Escape and returns keyboard focus", async () => {
  const {remove, rename} = setup();
  const opener = screen.getByRole("button", {name: "Conversation actions"});
  opener.focus();
  fireEvent.click(opener);
  expect(opener).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", {name: "Rename conversation"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "Delete conversation"})).toBeInTheDocument();
  fireEvent.keyDown(document.activeElement!, {key: "Escape"});
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(opener).toHaveFocus();
  expect(opener).toHaveAttribute("aria-expanded", "false");
  expect(remove).not.toHaveBeenCalled();
  expect(rename).not.toHaveBeenCalled();
});

it("focuses the rename field and cancels without saving", async () => {
  const {rename} = setup();
  chooseAction("Rename conversation");
  const input = screen.getByRole("textbox", {name: "Conversation title"});
  expect(input).toHaveFocus();
  fireEvent.change(input, {target: {value: "Uncommitted name"}});
  fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(rename).not.toHaveBeenCalled();
});
