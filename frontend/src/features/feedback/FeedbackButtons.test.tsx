import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createMemoryRouter, Link, Outlet, RouterProvider } from "react-router";
import { api } from "../../api/client";
import { UnsavedChangesProvider } from "../../components/UnsavedChanges";
import { FeedbackButtons } from "./FeedbackButtons";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test-token" }) }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("shows a failed helpful rating without opening the note form and allows retry", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("Feedback could not be saved.")).mockResolvedValueOnce({} as never);
  render(<FeedbackButtons question="When is payroll?" answer="On the last working day."/>);
  const helpful = screen.getByRole("button", {name: "Helpful"});
  helpful.focus();
  expect(helpful).toHaveFocus();
  fireEvent.click(helpful);

  expect(await screen.findByRole("alert")).toHaveTextContent("Feedback could not be saved. Please try again.");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(helpful).toBeEnabled();
  fireEvent.click(helpful);

  expect(await screen.findByRole("status")).toHaveTextContent("Thanks — knowledge admins see this feedback without your identity.");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  expect(api).toHaveBeenLastCalledWith("/api/v1/feedback", "test-token", {
    method: "POST",
    body: JSON.stringify({rating: 5, question: "When is payroll?", answer: "On the last working day.", comment: ""}),
  });
});

it("keeps an unsent feedback note when navigation is cancelled and discards it only after confirmation", async () => {
  const router = createMemoryRouter([{element: <UnsavedChangesProvider><Outlet/></UnsavedChangesProvider>, children: [
    {path: "/employee", element: <><FeedbackButtons question="When is payroll?" answer="On the last working day."/><Link to="/requests">My requests</Link></>},
    {path: "/requests", element: <h1>Requests</h1>},
  ]}], {initialEntries: ["/employee"]});
  render(<RouterProvider router={router}/>);
  fireEvent.click(screen.getByRole("button", {name: "Not helpful"}));
  const note = screen.getByRole("textbox", {name: /What should we improve/});
  fireEvent.change(note, {target: {value: "The policy needs a clearer example."}});
  fireEvent.click(screen.getByRole("link", {name: "My requests"}));
  expect(await screen.findByRole("dialog", {name: "Leave without saving?"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "Keep editing"}));
  expect(note).toHaveValue("The policy needs a clearer example.");
  expect(router.state.location.pathname).toBe("/employee");
  fireEvent.click(screen.getByRole("link", {name: "My requests"}));
  fireEvent.click(await screen.findByRole("button", {name: "Discard changes and leave"}));
  expect(await screen.findByRole("heading", {name: "Requests"})).toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});

it("locks the submitted note while sending and keeps it editable after failure", async () => {
  let rejectRequest!: (cause: Error) => void;
  vi.mocked(api).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
  render(<FeedbackButtons question="When is payroll?" answer="On the last working day."/>);
  fireEvent.click(screen.getByRole("button", {name: "Not helpful"}));
  const note = screen.getByRole("textbox", {name: /What should we improve/});
  fireEvent.change(note, {target: {value: "Please explain public holidays."}});
  fireEvent.click(screen.getByRole("button", {name: "Send feedback"}));
  expect(note).toBeDisabled();
  expect(screen.getByRole("button", {name: "Cancel"})).toBeDisabled();
  await act(async () => rejectRequest(new Error("Connection lost.")));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost.");
  expect(note).toBeEnabled();
  expect(note).toHaveValue("Please explain public holidays.");
  expect(api).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(vi.mocked(api).mock.calls[0][2]?.body)).comment).toBe("Please explain public holidays.");
});
