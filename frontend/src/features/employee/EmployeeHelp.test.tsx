import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, expect, it } from "vitest";
import { UnsavedChangesProvider, useUnsavedChanges } from "../../components/UnsavedChanges";
import { EmployeeHelp } from "./EmployeeHelp";

afterEach(cleanup);

function Workspace({ dirty = false }: { dirty?: boolean }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useUnsavedChanges(dirty);
  return <><output aria-label="Current location">{location.pathname + location.search}</output><button onClick={() => setOpen(true)}>Help</button><EmployeeHelp open={open} onOpenChange={setOpen}/></>;
}

function setup(path = "/home", dirty = false) {
  render(<MemoryRouter initialEntries={[path]}><UnsavedChangesProvider><Workspace dirty={dirty}/></UnsavedChangesProvider></MemoryRouter>);
  const opener = screen.getByRole("button", {name: "Help"});
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

it.each([
  ["Open my chats", "/employee"],
  ["Create a request", "/requests?new=1"],
  ["Open my requests", "/requests"],
])("opens the existing destination for %s", async (name, destination) => {
  setup();
  expect(screen.getByRole("dialog", {name: "Getting help"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name}));
  expect(screen.getByLabelText("Current location")).toHaveTextContent(destination);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("keeps an existing conversation and unsent draft when returning to its chat", async () => {
  setup("/employee?conversation=saved-dialog", true);
  fireEvent.click(screen.getByRole("button", {name: "Open my chats"}));
  expect(screen.getByLabelText("Current location")).toHaveTextContent("/employee?conversation=saved-dialog");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("protects unsaved work before navigating to request creation", async () => {
  setup("/employee?conversation=saved-dialog", true);
  fireEvent.click(screen.getByRole("button", {name: "Create a request"}));
  expect(screen.getByRole("dialog", {name: "Leave without saving?"})).toBeInTheDocument();
  expect(screen.getByLabelText("Current location")).toHaveTextContent("/employee?conversation=saved-dialog");
  fireEvent.click(screen.getByRole("button", {name: "Keep editing"}));
  const help = await screen.findByRole("dialog", {name: "Getting help"});
  fireEvent.click(within(help).getByRole("button", {name: "Create a request"}));
  fireEvent.click(await screen.findByRole("button", {name: "Discard changes and leave"}));
  expect(screen.getByLabelText("Current location")).toHaveTextContent("/requests?new=1");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("explains follow-up and private notifications and dismisses with keyboard focus restored", async () => {
  const opener = setup();
  const help = screen.getByRole("dialog", {name: "Getting help"});
  expect(help).toHaveTextContent("Reply to manager");
  expect(help).toHaveTextContent("Request reconsideration");
  expect(help).toHaveTextContent("Approval, rejection and other status changes are not sent automatically");
  fireEvent.keyDown(document.activeElement!, {key: "Escape"});
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(opener).toHaveFocus();
  expect(screen.getByLabelText("Current location")).toHaveTextContent("/home");
});
