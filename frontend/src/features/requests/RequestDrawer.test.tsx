import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { WorkflowRequest } from "../../api/types";
import { RequestDrawer } from "./RequestDrawer";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test", user: { id: "employee.demo", role: "employee", manager_id: "manager.demo" } }) }));
afterEach(cleanup);
const draft: WorkflowRequest = { id: "draft-one", number: 1, title: "Employment letter", priority: "normal", revision: 2, review_round: 1, type: "document", type_label: "Document", start_date: null, end_date: null, duration_days: null, comment: "Confirm employment dates", applicant: "employee.demo", approver: "manager.demo", status: "draft", created_at: "2030-01-01", updated_at: "2030-01-01" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async path => path.includes("request-options") ? { managers: [{ id: "manager.demo", display_name: "Demo Manager" }] } as never : { request: draft } as never);
});
function mount(initial?: WorkflowRequest, onOpenRequest = vi.fn()) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  function Form() {
    const [open, setOpen] = useState(true);
    return <><button onClick={() => setOpen(true)}>Open form</button><RequestDrawer open={open} onOpenChange={setOpen} initial={initial} onOpenRequest={onOpenRequest}/></>;
  }
  render(<QueryClientProvider client={cache}><Form/></QueryClientProvider>);
}

it("keeps edited draft values when close is cancelled, and discards only unsaved values", async () => {
  mount(draft);
  await screen.findByText("Demo Manager");
  fireEvent.change(screen.getByLabelText("Title *"), { target: { value: "Changed locally" } });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(await screen.findByRole("heading", { name: "Save your changes?" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Continue editing" }));
  expect(screen.getByLabelText("Title *")).toHaveValue("Changed locally");
  fireEvent.click(screen.getByRole("button", { name: "Close drawer" }));
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Open form" }));
  expect(await screen.findByLabelText("Title *")).toHaveValue("Employment letter");
});

it("protects Escape and saves the draft before closing when requested", async () => {
  mount(draft);
  fireEvent.change(await screen.findByLabelText("Description *"), { target: { value: "Updated details" } });
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape", code: "Escape", keyCode: 27 });
  fireEvent.click(await screen.findByRole("button", { name: "Save draft and close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/v1/requests/draft-one");
  expect(writes[0][2]?.method).toBe("PATCH");
  expect(JSON.parse(String(writes[0][2]?.body))).toMatchObject({ comment: "Updated details", expected_revision: 2 });
});

it("keeps the confirmation open and the draft text intact if saving fails", async () => {
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method) throw new Error("The server is unavailable. Try again.");
    return { managers: [] } as never;
  });
  mount(draft);
  fireEvent.change(await screen.findByLabelText("Title *"), { target: { value: "Keep my changes" } });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save draft and close" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The server is unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Continue editing" }));
  expect(screen.getByLabelText("Title *")).toHaveValue("Keep my changes");
});

it("closes an unchanged form without a discard prompt", async () => {
  mount(draft);
  await screen.findByLabelText("Title *");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("heading", { name: "Save your changes?" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("explains invalid details, focuses the first field, and still saves an incomplete private draft", async () => {
  mount();
  await screen.findByText("Demo Manager");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByLabelText("Title *")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Description *")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("heading", { name: "What do you need?" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("Title *")).toHaveFocus());
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByRole("heading", { name: "Draft saved" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "REQ-000001" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("private draft is saved");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/v1/requests");
});

it("keeps details, dates and priority when moving backwards and submits only after review", async () => {
  const openRequest = vi.fn();
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return { managers: [{ id: "manager.demo", display_name: "Demo Manager" }] } as never;
    const fields = JSON.parse(String(options?.body));
    return { request: { ...draft, ...fields, id: "new-request", number: 42, status: path.endsWith("/submit") ? "submitted" : "draft", revision: path.endsWith("/submit") ? 2 : 1 } } as never;
  });
  mount(undefined, openRequest);
  await screen.findByText("Demo Manager");
  fireEvent.change(screen.getByLabelText("Title *"), { target: { value: "Family vacation" } });
  fireEvent.change(screen.getByLabelText("Description *"), { target: { value: "Requesting time away from work" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "When and how urgent?" })).toHaveFocus());
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Choose both a start and an end date");
  await waitFor(() => expect(screen.getByLabelText("Starts *")).toHaveFocus());
  fireEvent.change(screen.getByLabelText("Starts *"), { target: { value: "2030-02-03" } });
  fireEvent.change(screen.getByLabelText("Ends *"), { target: { value: "2030-02-02" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent("End date cannot be earlier");
  fireEvent.change(screen.getByLabelText("Ends *"), { target: { value: "2030-02-07" } });
  fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "high" } });
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByLabelText("Title *")).toHaveValue("Family vacation");
  expect(screen.getByLabelText("Description *")).toHaveValue("Requesting time away from work");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByLabelText("Priority")).toHaveValue("high");
  expect(screen.getByLabelText("Starts *")).toHaveValue("2030-02-03");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("heading", { name: "Review your request" })).toBeInTheDocument();
  expect(screen.getByText("2030-02-03 → 2030-02-07 · 5 calendar days")).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
  expect(await screen.findByRole("heading", { name: "Request submitted" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "REQ-000042" })).toBeInTheDocument();
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(2);
  expect(JSON.parse(String(writes[1][2]?.body))).toMatchObject({ title: "Family vacation", comment: "Requesting time away from work", type: "pto", priority: "high", start_date: "2030-02-03", end_date: "2030-02-07", expected_revision: 1 });
  fireEvent.click(screen.getByRole("button", { name: "Open request" }));
  expect(openRequest).toHaveBeenCalledWith("new-request");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("saves an edited draft on the timing step without requiring dates or creating another request", async () => {
  mount({ ...draft, type: "pto", type_label: "Vacation / PTO" });
  await screen.findByText("Demo Manager");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "urgent" } });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByRole("heading", { name: "Draft saved" })).toBeInTheDocument();
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][2]?.method).toBe("PATCH");
  expect(JSON.parse(String(writes[0][2]?.body))).toMatchObject({ priority: "urgent", start_date: null, end_date: null, expected_revision: 2 });
});

it.each([false, true])("keeps optional dates expanded and focus visible when editing and clearing them (saved dates: %s)", async hasDates => {
  mount({ ...draft, start_date: hasDates ? "2030-02-03" : null, end_date: hasDates ? "2030-02-07" : null });
  await screen.findByText("Demo Manager");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "When and how urgent?" })).toHaveFocus());
  const summary = screen.getByText("Add an optional date range");
  const details = summary.closest("details")!;
  if (!hasDates) {
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(summary);
  }
  await waitFor(() => expect(details).toHaveAttribute("open"));
  const start = screen.getByLabelText("Starts");
  const end = screen.getByLabelText("Ends");
  start.focus();
  fireEvent.change(start, { target: { value: "2030-02-04" } });
  expect(details).toHaveAttribute("open");
  expect(start).toHaveFocus();
  fireEvent.change(end, { target: { value: "2030-02-08" } });
  fireEvent.change(start, { target: { value: "" } });
  end.focus();
  fireEvent.change(end, { target: { value: "" } });
  expect(details).toHaveAttribute("open");
  expect(end).toHaveFocus();
  expect(end).toBeVisible();
  fireEvent.click(summary);
  await waitFor(() => expect(details).not.toHaveAttribute("open"));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("keeps the review and entries after a failed submit and reuses the persisted draft on retry", async () => {
  let submits = 0;
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return { managers: [{ id: "manager.demo", display_name: "Demo Manager" }] } as never;
    if (path.endsWith("/submit") && ++submits === 1) throw new Error("Server unavailable");
    return { request: { ...draft, ...JSON.parse(String(options?.body)), revision: 2, status: path.endsWith("/submit") ? "submitted" : "draft" } } as never;
  });
  mount();
  await screen.findByText("Demo Manager");
  fireEvent.change(screen.getByLabelText("Category *"), { target: { value: "document" } });
  fireEvent.change(screen.getByLabelText("Title *"), { target: { value: "Proof of employment" } });
  fireEvent.change(screen.getByLabelText("Description *"), { target: { value: "Please confirm my current role" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByText("Proof of employment")).toBeInTheDocument();
  expect(screen.getByText("Please confirm my current role")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
  expect(await screen.findByRole("heading", { name: "Request submitted" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method).map(call => call[0])).toEqual(["/api/v1/requests", "/api/v1/requests/draft-one/submit", "/api/v1/requests/draft-one/submit"]);
});
