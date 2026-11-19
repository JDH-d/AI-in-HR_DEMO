import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider, useNavigate, useSearchParams } from "react-router";
import { api, downloadFile } from "../../api/client";
import type { RequestDetail } from "../../api/types";
import { RequestDetailDrawer } from "./RequestDetailDrawer";
import { UnsavedChangesProvider } from "../../components/UnsavedChanges";

vi.mock("../../api/client", () => ({ api: vi.fn(), downloadFile: vi.fn() }));
const identity = vi.hoisted(() => ({ role: "manager" }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test", user: { role: identity.role } }) }));
afterEach(cleanup);
let detail: RequestDetail;
beforeEach(() => {
  vi.clearAllMocks();
  identity.role = "manager";
  detail = {
    request: { id: "r1", number: 1, title: "Letter", priority: "normal", revision: 3, review_round: 1, type: "document", type_label: "Document", start_date: null, end_date: null, duration_days: null, comment: "Relevant facts", applicant: "employee.demo", approver: "manager.demo", status: "in_review", created_at: "2030-01-01", updated_at: "2030-01-01" },
    events: [], comments: [], attachments: [], allowed_actions: ["approve", "reject", "request_information"], procedure: "The same relevant criteria for everyone.", policy_version: "v1",
  };
  vi.mocked(api).mockImplementation(async path => path.includes("request-options") ? { managers: [] } as never : structuredClone(detail) as never);
});

function mount(onClose = vi.fn()) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  cache.setQueryData(["requests"], { requests: [] });
  cache.setQueryData(["manager-requests"], { requests: [] });
  render(<QueryClientProvider client={cache}><RequestDetailDrawer id="r1" onClose={onClose}/></QueryClientProvider>);
  return cache;
}

it.each([
  ["request_information", "Request information", false],
  ["approve", "Approve", true],
  ["reject", "Reject", true],
  ["complete", "Mark completed", false],
] as const)("requires request-specific information when using a %s template", async (action, label, decision) => {
  detail.allowed_actions = [action];
  if (action === "complete") detail.request.status = "approved";
  mount();
  fireEvent.click(await screen.findByRole("button", { name: label }));
  fireEvent.click(screen.getByText("Response templates", { selector: "summary" }));
  expect(screen.getByLabelText("Reason or additional information *")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Use template" }));
  const reason = screen.getByLabelText("Reason or additional information *") as HTMLTextAreaElement;
  expect(reason.value).toContain("[[");
  expect(screen.getByRole("status")).toHaveTextContent("Replace every [[placeholder]]");
  if (decision) {
    expect(screen.getByLabelText("Relevant policy or objective criteria *")).toHaveValue("");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("Relevant policy or objective criteria *"), { target: { value: "Published request policy, section 2" } });
    fireEvent.click(screen.getByRole("checkbox"));
  }
  expect(screen.getByRole("button", { name: label })).toBeDisabled();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.change(reason, { target: { value: "The supplied information confirms coverage for the dates in this request." } });
  expect(screen.getByRole("button", { name: label })).toBeEnabled();
  expect(screen.queryByText(/Replace every \[\[placeholder\]\]/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Back to request" }));
  fireEvent.click(screen.getByRole("button", { name: `Continue ${label}` }));
  expect(screen.getByLabelText("Reason or additional information *")).toHaveValue("The supplied information confirms coverage for the dates in this request.");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("does not offer Manager templates or review targets in an Employee action", async () => {
  identity.role = "employee";
  detail.request.status = "needs_information";
  detail.request.manager_attention = { due_at: "2030-01-06T00:00:00Z", overdue: true, reasons: ["overdue"] };
  detail.allowed_actions = ["provide_information"];
  mount();
  const reply = await screen.findByRole("button", { name: "Reply to manager" });
  expect(screen.queryByRole("region", { name: "Review target" })).not.toBeInTheDocument();
  fireEvent.click(reply);
  expect(screen.queryByText("Response templates", { selector: "summary" })).not.toBeInTheDocument();
});

it("appending a template keeps notes and policy text but requires fresh equal-treatment confirmation", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  fireEvent.change(screen.getByLabelText("Reason or additional information *"), { target: { value: "Existing request-specific facts." } });
  fireEvent.change(screen.getByLabelText("Relevant policy or objective criteria *"), { target: { value: "Published policy section 2" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("Response templates", { selector: "summary" }));
  fireEvent.click(screen.getByRole("button", { name: "Append template" }));
  expect((screen.getByLabelText("Reason or additional information *") as HTMLTextAreaElement).value).toMatch(/^Existing request-specific facts\.\n\nI reviewed/);
  expect(screen.getByLabelText("Relevant policy or objective criteria *")).toHaveValue("Published policy section 2");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("keeps review actions available while a failed manager list is retried, but blocks stale reassignment", async () => {
  let failManagers = false;
  vi.mocked(api).mockImplementation(async path => {
    if (path.includes("request-options")) {
      if (failManagers) throw new Error("Offline");
      return { managers: [{ id: "other.manager", display_name: "Other manager" }] } as never;
    }
    return structuredClone(detail) as never;
  });
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Change assigned manager" }));
  fireEvent.change(screen.getByLabelText("Reassign to"), { target: { value: "other.manager" } });
  fireEvent.change(screen.getByLabelText("Reason for reassignment"), { target: { value: "Coverage during scheduled leave" } });
  failManagers = true;
  await cache.invalidateQueries({ queryKey: ["request-options"] });
  expect(await screen.findByRole("alert")).toHaveTextContent("list of managers could not be loaded");
  expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Reassign" })).toBeDisabled();
  expect(screen.getByLabelText("Reassign to")).toBeDisabled();
  expect(screen.getByLabelText("Reason for reassignment")).toHaveValue("Coverage during scheduled leave");
  failManagers = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry manager list" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Reassign" })).toBeEnabled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Reassign to")).toHaveValue("other.manager");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it.each([false, true])("blocks a removed reassignment recipient after a successful manager-list refresh (confirmation open: %s)", async confirmationOpen => {
  let managers = [
    { id: "other.manager", display_name: "Other manager" },
    { id: "cover.manager", display_name: "Cover manager" },
  ];
  vi.mocked(api).mockImplementation(async path => path.includes("request-options")
    ? { managers } as never : structuredClone(detail) as never);
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Change assigned manager" }));
  fireEvent.change(screen.getByLabelText("Reassign to"), { target: { value: "other.manager" } });
  fireEvent.change(screen.getByLabelText("Reason for reassignment"), { target: { value: "Coverage during scheduled leave" } });
  expect(screen.getByRole("button", { name: "Reassign" })).toBeEnabled();
  if (confirmationOpen) {
    fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "Keep this unsent note" } });
    fireEvent.click(screen.getByRole("button", { name: "Reassign" }));
    expect(screen.getByRole("heading", { name: "Reassign with unsent changes?" })).toBeInTheDocument();
  }
  managers = [{ id: "cover.manager", display_name: "Cover manager" }];
  await cache.invalidateQueries({ queryKey: ["request-options"] });
  expect(await screen.findByRole("alert")).toHaveTextContent("selected manager is no longer available");
  expect(screen.queryByRole("heading", { name: "Reassign with unsent changes?" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Reassign to")).toHaveValue("");
  expect(screen.getByLabelText("Reassign to")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "Reassign" })).toBeDisabled();
  expect(screen.getByLabelText("Reason for reassignment")).toHaveValue("Coverage during scheduled leave");
  if (confirmationOpen) expect(screen.getByLabelText("Add comment")).toHaveValue("Keep this unsent note");
  fireEvent.click(screen.getByRole("button", { name: "Reassign" }));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.change(screen.getByLabelText("Reassign to"), { target: { value: "cover.manager" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reassign" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Reassign" }));
  if (confirmationOpen) fireEvent.click(screen.getByRole("button", { name: "Reassign and discard unsent changes" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method)).toHaveLength(1));
  const post = vi.mocked(api).mock.calls.find(call => call[2]?.method)!;
  expect(JSON.parse(String(post[2]?.body))).toEqual({ assignee: "cover.manager", comment: "Coverage during scheduled leave", expected_revision: 3 });
});

it.each([
  ["in_review", "2030-01-06T00:00:00Z", true, "Review overdue"],
  ["submitted", "2030-01-06T00:00:00Z", false, "Review target"],
  ["needs_information", null, false, "Review paused — waiting for employee"],
] as const)("explains the Manager review target for %s without changing the request", async (status, due, overdue, heading) => {
  detail.request.status = status;
  detail.request.manager_attention = { due_at: due, overdue, reasons: overdue ? ["overdue"] : [] };
  mount();
  const target = await screen.findByRole("region", { name: "Review target" });
  expect(within(target).getByRole("heading", { name: heading })).toBeInTheDocument();
  expect(target).toHaveTextContent("5 calendar days");
  if (due) expect(target.querySelector("time")).toHaveAttribute("dateTime", due);
  else expect(target.querySelector("time")).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("clears an attachment download error after retry without changing the request or unsent text", async () => {
  detail.attachments = [{ id: "attachment-one", filename: "evidence.txt", content_type: "text/plain", size: 120, sha256: "test-hash", author: "employee.demo", created_at: "2030-01-01" }];
  vi.mocked(downloadFile).mockRejectedValueOnce(new Error("Download failed. Try again.")).mockResolvedValueOnce(undefined);
  mount();
  const attachment = await screen.findByRole("button", { name: "evidence.txt" });
  fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "Keep my unsent evidence" } });
  fireEvent.click(attachment);
  expect(await screen.findByRole("alert")).toHaveTextContent("Download failed");
  fireEvent.click(attachment);
  await waitFor(() => expect(vi.mocked(downloadFile)).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(vi.mocked(downloadFile)).toHaveBeenLastCalledWith("/api/v1/requests/r1/attachments/attachment-one", "test", "evidence.txt");
  expect(screen.getByLabelText("Add comment")).toHaveValue("Keep my unsent evidence");
  expect(screen.getByRole("button", { name: "evidence.txt" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("requires reason, objective criteria, equal-treatment confirmation and an explicit decision confirmation", async () => {
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
  expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Reason or additional information *"), { target: { value: "A required document is missing" } });
  fireEvent.change(screen.getByLabelText("Relevant policy or objective criteria *"), { target: { value: "Policy section 2" } });
  expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Go back" }));
  expect(screen.getByLabelText("Reason or additional information *")).toHaveValue("A required document is missing");
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm Reject" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(true));
  const call = vi.mocked(api).mock.calls.find(call => call[2]?.method === "POST")!;
  expect(call[0]).toBe("/api/v1/requests/r1/actions/reject");
  expect(JSON.parse(String(call[2]?.body))).toEqual({ expected_revision: 3, comment: "A required document is missing", basis: "Policy section 2", fair_review_confirmed: true });
  await waitFor(() => expect(cache.getQueryState(["requests"])?.isInvalidated).toBe(true));
  expect(cache.getQueryState(["manager-requests"])?.isInvalidated).toBe(true);
}, 15000);

it("uses a page for detailed work and discards unsent text with one confirmation", async () => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  function RequestRoute() {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    return params.has("request") ? <RequestDetailDrawer id="r1" presentation="page" onClose={() => navigate("/requests")}/> : <p>Request list</p>;
  }
  const router = createMemoryRouter([{ path: "/requests", element: <UnsavedChangesProvider><RequestRoute/></UnsavedChangesProvider> }], { initialEntries: ["/requests?request=r1"] });
  render(<QueryClientProvider client={cache}><RouterProvider router={router}/></QueryClientProvider>);
  await screen.findByRole("region", { name: "Available actions" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "Unsent evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Back to requests" }));
  expect(await screen.findByRole("heading", { name: "Leave without sending?" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Discard unsent changes" }));
  expect(await screen.findByText("Request list")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Leave without saving?" })).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  vi.restoreAllMocks();
});

it("preserves a failed comment and retries with the refreshed revision", async () => {
  let attempts = 0;
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method === "POST" && ++attempts === 1) {
      detail.request.revision = 4;
      throw new Error("This request changed. Review the latest information.");
    }
    return path.includes("request-options") ? { managers: [] } as never : structuredClone(detail) as never;
  });
  mount();
  await screen.findByRole("region", { name: "Available actions" });
  fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "My additional evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This request changed");
  expect(screen.getByLabelText("Add comment")).toHaveValue("My additional evidence");
  await waitFor(() => expect(screen.getByRole("button", { name: "Add comment" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
  await waitFor(() => expect(attempts).toBe(2));
  const calls = vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST");
  expect(JSON.parse(String(calls[1][2]?.body)).expected_revision).toBe(4);
  await waitFor(() => expect(screen.getByLabelText("Add comment")).toHaveValue(""));
}, 15000);

it("requires fresh decision confirmation when another revision replaces the reviewed data", async () => {
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  fireEvent.change(screen.getByLabelText("Reason or additional information *"), { target: { value: "Reason based on revision three" } });
  fireEvent.change(screen.getByLabelText("Relevant policy or objective criteria *"), { target: { value: "Policy section 2" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  detail.request.revision = 4;
  detail.comments = [{ id: "new", author: "employee.demo", body: "New evidence changes the facts", created_at: "2030-01-02" }];
  await cache.invalidateQueries({ queryKey: ["request-detail", "r1"] });
  await screen.findByText("New evidence changes the facts");
  expect(screen.queryByRole("button", { name: "Confirm Approve" })).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByLabelText("Reason or additional information *")).toHaveValue("Reason based on revision three");
  expect(await screen.findByText(/The request changed. Your unsent text is kept./)).toHaveTextContent("Decisions need fresh confirmation.");
}, 15000);

it("does not warn Employee about a conflict after submitting their own edited draft", async () => {
  identity.role = "employee";
  detail.request.status = "draft";
  detail.allowed_actions = ["submit", "cancel"];
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return { managers: [] } as never;
    if (options?.method === "POST") {
      const body = JSON.parse(String(options.body));
      detail.request = { ...detail.request, title: body.title, status: "submitted", revision: 4 };
      detail.allowed_actions = ["cancel"];
      return { request: structuredClone(detail.request) } as never;
    }
    return structuredClone(detail) as never;
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit or submit draft" }));
  fireEvent.change(await screen.findByLabelText("Title *"), { target: { value: "My updated letter request" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open request" }));
  await screen.findByText("Your manager will review this request.");
  expect(screen.queryByText(/The request changed./)).not.toBeInTheDocument();
  expect(screen.queryByText(/Decisions need fresh confirmation./)).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST")).toHaveLength(1);
});

it("keeps unsent text but disables stale actions until a failed refresh succeeds", async () => {
  const cache = mount();
  await screen.findByRole("region", { name: "Available actions" });
  fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "Evidence to send once connected" } });
  vi.mocked(api).mockRejectedValue(new Error("Offline"));
  await cache.invalidateQueries({ queryKey: ["request-detail", "r1"] });
  expect(await screen.findByRole("alert")).toHaveTextContent("reload successfully before making changes");
  expect(screen.getByText("Relevant facts")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Add comment" })).toBeDisabled();
  expect(screen.getByLabelText("Add comment")).toHaveValue("Evidence to send once connected");
  fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  vi.mocked(api).mockResolvedValue(structuredClone(detail) as never);
  fireEvent.click(screen.getByRole("button", { name: "Reload request" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Add comment" })).toBeEnabled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it.each([403, 404])("hides cached request content when refresh reports %i", async status => {
  const cache = mount();
  await screen.findByText("Relevant facts");
  vi.mocked(api).mockRejectedValue(Object.assign(new Error("Request unavailable"), { status }));
  await cache.invalidateQueries({ queryKey: ["request-detail", "r1"] });
  expect(await screen.findByRole("alert")).toHaveTextContent("no longer available to you");
  expect(screen.queryByText("Relevant facts")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Letter" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Available actions" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Add comment")).not.toBeInTheDocument();
});

it("requires an explicit discard before reassignment closes other unsent work", async () => {
  const onClose = vi.fn();
  vi.mocked(api).mockImplementation(async path => path.includes("request-options") ? { managers: [{ id: "other.manager", display_name: "Other manager" }] } as never : structuredClone(detail) as never);
  mount(onClose);
  fireEvent.click(await screen.findByRole("button", { name: "Change assigned manager" }));
  fireEvent.change(await screen.findByLabelText("Reassign to"), { target: { value: "other.manager" } });
  fireEvent.change(screen.getByLabelText("Reason for reassignment"), { target: { value: "Cover during scheduled leave" } });
  fireEvent.change(screen.getByLabelText("Add comment"), { target: { value: "Separate unsent evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Reassign" }));
  expect(await screen.findByRole("heading", { name: "Reassign with unsent changes?" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByLabelText("Add comment")).toHaveValue("Separate unsent evidence");
  fireEvent.click(screen.getByRole("button", { name: "Reassign" }));
  fireEvent.click(screen.getByRole("button", { name: "Reassign and discard unsent changes" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  const posts = vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/v1/requests/r1/assign");
  expect(JSON.parse(String(posts[0][2]?.body))).toEqual({ assignee: "other.manager", comment: "Cover during scheduled leave", expected_revision: 3 });
});

it.each([
  ["manager", "submitted", "start_review", "Start review", false],
  ["manager", "in_review", "request_information", "Request information", false],
  ["manager", "in_review", "approve", "Approve", true],
  ["manager", "approved", "complete", "Mark completed", true],
  ["employee", "draft", "cancel", "Cancel request", true],
  ["employee", "needs_information", "provide_information", "Provide information", false],
  ["employee", "approved", "appeal", "Request reconsideration", true],
  ["employee", "rejected", "appeal", "Request reconsideration", true],
  ["employee", "completed", "appeal", "Request reconsideration", true],
] as const)("records the authorized %s action from %s: %s", async (role, status, action, label, confirmation) => {
  identity.role = role;
  detail.request.status = status;
  detail.allowed_actions = [action];
  mount();
  if (action !== "start_review") fireEvent.click(await screen.findByRole("button", { name: action === "provide_information" ? "Reply to manager" : label }));
  else await screen.findByRole("button", { name: label });
  if (role === "employee") {
    expect(screen.queryByRole("region", { name: "Assignment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  }
  const reasonLabel = role !== "employee" ? "Reason or additional information *" : action === "provide_information" ? "Your response *" : action === "appeal" ? "Reason for reconsideration *" : "Reason for cancellation *";
  if (action !== "start_review") fireEvent.change(screen.getByLabelText(reasonLabel), { target: { value: "Relevant information for this action" } });
  if (action === "approve") {
    fireEvent.change(screen.getByLabelText("Relevant policy or objective criteria *"), { target: { value: "Relevant published criteria" } });
    fireEvent.click(screen.getByRole("checkbox"));
  }
  fireEvent.click(screen.getByRole("button", { name: action === "provide_information" ? "Send reply" : label }));
  if (confirmation) {
    expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: `Confirm ${label}` }));
  }
  const success = role !== "employee" ? `${label} recorded. The request and history are up to date.` : action === "provide_information" ? "Your reply was sent to the assigned manager. The request is back in review." : action === "appeal" ? "Reconsideration requested. The original decision is preserved in the history." : "Request cancelled. The saved request and history remain available.";
  await waitFor(() => expect(screen.getByText(success)).toBeInTheDocument());
  const posts = vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe(`/api/v1/requests/r1/actions/${action}`);
  expect(JSON.parse(String(posts[0][2]?.body)).expected_revision).toBe(3);
});

it("does not offer an action or attachment upload for a cancelled request", async () => {
  detail.request.status = "cancelled";
  detail.allowed_actions = [];
  mount();
  await screen.findByText("Relevant facts");
  expect(screen.queryByRole("region", { name: "Available actions" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Choose attachment")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Add comment")).toBeInTheDocument();
});

it("keeps review notes when the focused action form closes and requires explicit discard", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
  expect(screen.getByRole("dialog", { name: "Reject · REQ-000001" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Reason or additional information *"), { target: { value: "Keep this explanation until I have checked the evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Back to request" }));
  expect(screen.queryByRole("dialog", { name: "Reject · REQ-000001" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Continue Reject" }));
  expect(screen.getByLabelText("Reason or additional information *")).toHaveValue("Keep this explanation until I have checked the evidence");
  fireEvent.click(screen.getByRole("button", { name: "Back to request" }));
  fireEvent.click(screen.getByRole("button", { name: "Discard review notes" }));
  fireEvent.click(screen.getByRole("button", { name: "Keep notes" }));
  expect(screen.getByRole("button", { name: "Continue Reject" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Discard review notes" }));
  fireEvent.click(screen.getByRole("button", { name: "Discard notes" }));
  expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
});

it("closes a stale action form when the action is no longer allowed and keeps notes read-only", async () => {
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  fireEvent.change(screen.getByLabelText("Reason or additional information *"), { target: { value: "My unsent reasoning" } });
  detail.request.revision = 4;
  detail.request.status = "cancelled";
  detail.allowed_actions = [];
  await cache.invalidateQueries({ queryKey: ["request-detail", "r1"] });
  expect(await screen.findByRole("region", { name: "Unsent review notes" })).toHaveTextContent("My unsent reasoning");
  expect(screen.queryByRole("dialog", { name: "Approve · REQ-000001" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm Approve" })).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
});

it.each([
  ["draft", "Finish your draft", "Draft"],
  ["submitted", "Waiting for review", "Submitted"],
  ["in_review", "Your manager is reviewing it", "Review"],
  ["needs_information", "Your reply is needed", "Review"],
  ["approved", "Your request was approved", "Decision"],
  ["rejected", "Your request was rejected", "Decision"],
  ["completed", "Your request is complete", "Completed"],
  ["cancelled", "Your request is cancelled", null],
])("explains Employee progress for %s without inventing a completed review", async (status, title, current) => {
  identity.role = "employee";
  detail.request.status = status!;
  detail.allowed_actions = [];
  mount();
  const progress = await screen.findByRole("region", {name: "Request progress"});
  expect(within(progress).getByRole("heading", {name: title!})).toBeInTheDocument();
  expect(within(progress).getByRole("heading", {name: "What happens next"})).toBeInTheDocument();
  if (current) expect(progress.querySelector('[aria-current="step"]')).toHaveTextContent(`${current}: current stage`);
  else expect(within(progress).queryByRole("list")).not.toBeInTheDocument();
  if (status === "rejected") {
    expect(within(progress).queryByText("Completed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name:"Request reconsideration"})).not.toBeInTheDocument();
    expect(progress).toHaveTextContent("Reconsideration is not currently available");
  }
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("keeps an Employee reply after a conflict and retries the information action with the fresh revision", async () => {
  identity.role = "employee";
  detail.request.status = "needs_information";
  detail.allowed_actions = ["provide_information", "cancel"];
  detail.events = [{id:"question", event_type:"request_information", from_status:"in_review", to_status:"needs_information", actor:"manager.demo", details:{comment:"Which dates should the letter cover?"}, created_at:"2030-01-02T10:00:00Z"}];
  let attempts = 0;
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return {managers:[]} as never;
    if (options?.method === "POST") {
      attempts++;
      if (attempts === 1) { detail.request.revision = 4; throw new Error("This request changed. Review the latest information."); }
      const body = JSON.parse(String(options.body));
      detail.request.status = "in_review"; detail.request.revision = 5; detail.allowed_actions = ["cancel"];
      detail.events.push({id:"reply",event_type:"provide_information",from_status:"needs_information",to_status:"in_review",actor:"employee.demo",details:{comment:body.comment},created_at:"2030-01-03T10:00:00Z"});
      detail.comments.push({id:"reply-comment",author:"employee.demo",body:body.comment,created_at:"2030-01-03T10:00:00Z"});
    }
    return structuredClone(detail) as never;
  });
  mount();
  expect(await screen.findByRole("region", {name:"Information requested"})).toHaveTextContent("Which dates should the letter cover?");
  fireEvent.click(screen.getByRole("button", {name:"Reply to manager"}));
  expect(screen.getByRole("button", {name:"Send reply"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Your response *"), {target:{value:"Please cover January through March."}});
  fireEvent.click(screen.getByRole("button", {name:"Back to request"}));
  fireEvent.click(screen.getByRole("button", {name:"Continue reply"}));
  expect(screen.getByLabelText("Your response *")).toHaveValue("Please cover January through March.");
  fireEvent.click(screen.getByRole("button", {name:"Send reply"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("This request changed");
  expect(screen.getByLabelText("Your response *")).toHaveValue("Please cover January through March.");
  await waitFor(() => expect(screen.getByRole("button", {name:"Send reply"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name:"Send reply"}));
  expect(await screen.findByText("Your reply was sent to the assigned manager. The request is back in review.")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name:"Reply to manager"})).not.toBeInTheDocument();
  expect(screen.getByRole("region", {name:"Request progress"})).toHaveTextContent("Your manager is reviewing it");
  const posts = vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST");
  expect(posts).toHaveLength(2);
  expect(posts.map(call => call[0])).toEqual(["/api/v1/requests/r1/actions/provide_information", "/api/v1/requests/r1/actions/provide_information"]);
  expect(posts.map(call => JSON.parse(String(call[2]?.body)).expected_revision)).toEqual([3,4]);
  fireEvent.click(screen.getByText("History", {selector:"summary",exact:false}));
  const history = screen.getByRole("list", {name:"Request history events"});
  expect(history).toHaveTextContent("Manager requested information");
  expect(history).toHaveTextContent("Employee replied");
  expect(history).toHaveTextContent("Please cover January through March.");
}, 15000);

it("confirms reconsideration explicitly and keeps the original reason visible after reopening", async () => {
  identity.role = "employee";
  detail.request.status = "rejected"; detail.allowed_actions = ["appeal"];
  detail.events = [{id:"original",event_type:"decision_recorded",from_status:"in_review",to_status:"rejected",actor:"manager.demo",details:{comment:"A supporting document is missing.",basis:"Document policy section 2",review_round:1},created_at:"2030-01-02T10:00:00Z"}];
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return {managers:[]} as never;
    if (options?.method === "POST") {
      const body = JSON.parse(String(options.body));
      detail.request = {...detail.request,status:"submitted",revision:4,review_round:2}; detail.allowed_actions = ["cancel"];
      detail.events.push({id:"appeal",event_type:"reconsideration_requested",from_status:"rejected",to_status:"submitted",actor:"employee.demo",details:{comment:body.comment,previous_decision_id:"original"},created_at:"2030-01-03T10:00:00Z"});
    }
    return structuredClone(detail) as never;
  });
  mount();
  expect(await screen.findByRole("region", {name:"About reconsideration"})).toHaveTextContent("same assigned manager");
  fireEvent.click(screen.getByRole("button", {name:"Request reconsideration"}));
  expect(screen.getByRole("button", {name:"Request reconsideration"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Reason for reconsideration *"), {target:{value:"The requested supporting document is now available."}});
  fireEvent.click(screen.getByRole("button", {name:"Request reconsideration"}));
  expect(screen.getByRole("group", {name:"Confirm action"})).toHaveTextContent("status will return to Submitted");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(screen.getByRole("button", {name:"Go back"}));
  expect(screen.getByLabelText("Reason for reconsideration *")).toHaveValue("The requested supporting document is now available.");
  fireEvent.click(screen.getByRole("button", {name:"Request reconsideration"}));
  fireEvent.click(screen.getByRole("button", {name:"Confirm Request reconsideration"}));
  expect(await screen.findByText("Reconsideration requested. The original decision is preserved in the history.")).toBeInTheDocument();
  expect(screen.getByRole("region", {name:"Request progress"})).toHaveTextContent("Reconsideration · review 2");
  expect(screen.getByRole("region", {name:"Recorded decision"})).toHaveTextContent("A supporting document is missing.");
  expect(screen.getByText("Reconsideration is in progress. This earlier decision remains in the record.")).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST")).toHaveLength(1);
  expect(detail.events[0].id).toBe("original");
  fireEvent.click(screen.getByText("History", {selector:"summary",exact:false}));
  const history = screen.getByRole("list", {name:"Request history events"});
  expect(within(history).getAllByRole("listitem")).toHaveLength(2);
  expect(history).toHaveTextContent("Rejected decision recorded · review 1");
  expect(history).toHaveTextContent("Reconsideration requested");
}, 15000);

it("shows assignment changes, linked comments and attachment names in the saved history without writes", async () => {
  identity.role = "employee"; detail.allowed_actions = ["cancel"];
  detail.comments = [{id:"comment-one",author:"employee.demo",body:"A supporting note for this request.",created_at:"2030-01-03T10:00:00Z"}];
  detail.events = [
    {id:"assigned",event_type:"assignee_changed",from_status:"in_review",to_status:"in_review",actor:"manager.demo",details:{changes:{approver:{before:"manager.demo",after:"other.manager"}},comment:"Cover during leave."},created_at:"2030-01-02T10:00:00Z"},
    {id:"comment",event_type:"comment_added",from_status:"in_review",to_status:"in_review",actor:"employee.demo",details:{comment_id:"comment-one"},created_at:"2030-01-03T10:00:00Z"},
    {id:"file",event_type:"attachment_added",from_status:"in_review",to_status:"in_review",actor:"employee.demo",details:{attachment:{filename:"supporting-note.pdf"}},created_at:"2030-01-04T10:00:00Z"},
  ];
  mount();
  fireEvent.click(await screen.findByText("History", {selector:"summary",exact:false}));
  const history = screen.getByRole("list", {name:"Request history events"});
  expect(history).toHaveTextContent("Assigned manager changed");
  expect(history).toHaveTextContent("Assigned manager: manager.demo → other.manager");
  expect(history).toHaveTextContent("A supporting note for this request.");
  expect(history).toHaveTextContent("File: supporting-note.pdf");
  expect(Array.from(history.querySelectorAll("time")).map(time => time.dateTime)).toEqual(["2030-01-02T10:00:00Z", "2030-01-03T10:00:00Z", "2030-01-04T10:00:00Z"]);
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it.each(["request_information", "status_changed"])("keeps the actual %s question after reassignment and comments while awaiting a reply", async eventType => {
  identity.role = "employee"; detail.request.status = "needs_information";
  detail.allowed_actions = ["provide_information", "cancel"];
  detail.events = [
    {id:"question",event_type:eventType,from_status:"in_review",to_status:"needs_information",actor:"manager.demo",details:{comment:"What dates should the document cover?"},created_at:"2030-01-02T10:00:00Z"},
    {id:"assignment",event_type:"assignee_changed",from_status:"needs_information",to_status:"needs_information",actor:"manager.demo",details:{comment:"Cover during annual leave."},created_at:"2030-01-03T10:00:00Z"},
    {id:"comment",event_type:"comment_added",from_status:"needs_information",to_status:"needs_information",actor:"other.manager",details:{comment:"I am reviewing the supporting documents."},created_at:"2030-01-04T10:00:00Z"},
  ];
  mount();
  const information = await screen.findByRole("region", {name:"Information requested"});
  expect(information).toHaveTextContent("What dates should the document cover?");
  expect(information).not.toHaveTextContent("Cover during annual leave.");
  expect(information).not.toHaveTextContent("I am reviewing the supporting documents.");
  fireEvent.click(screen.getByRole("button", {name:"Reply to manager"}));
  const form = screen.getByRole("dialog", {name:"Reply to manager · REQ-000001"});
  expect(form).toHaveTextContent("What dates should the document cover?");
  expect(form).not.toHaveTextContent("Cover during annual leave.");
  expect(form).not.toHaveTextContent("I am reviewing the supporting documents.");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it.each(["refresh", "server revision", "another action", "refresh error"])("clears the previous reply confirmation on %s while keeping immediate action feedback", async followUp => {
  identity.role = "employee"; detail.request.status = "needs_information"; detail.allowed_actions = ["provide_information", "cancel"];
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.includes("request-options")) return {managers:[]} as never;
    if (options?.method === "POST") { detail.request.status = "in_review"; detail.request.revision = 4; detail.allowed_actions = ["cancel"]; }
    return structuredClone(detail) as never;
  });
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", {name:"Reply to manager"}));
  fireEvent.change(screen.getByLabelText("Your response *"), {target:{value:"Please cover January through March."}});
  fireEvent.click(screen.getByRole("button", {name:"Send reply"}));
  const success = "Your reply was sent to the assigned manager. The request is back in review.";
  expect(await screen.findByText(success)).toBeInTheDocument();
  if (followUp === "another action") {
    fireEvent.click(screen.getByRole("button", {name:"Cancel request"}));
    expect(screen.getByRole("dialog", {name:"Cancel request · REQ-000001"})).toBeInTheDocument();
  } else if (followUp === "refresh error") {
    vi.mocked(api).mockRejectedValue(new Error("Offline"));
    fireEvent.click(screen.getByRole("button", {name:"Refresh request"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be refreshed");
  } else {
    detail.request.status = "rejected"; detail.request.revision = 5; detail.allowed_actions = ["appeal"];
    if (followUp === "refresh") fireEvent.click(screen.getByRole("button", {name:"Refresh request"}));
    else await cache.invalidateQueries({queryKey:["request-detail", "r1"]});
    expect(await screen.findByRole("heading", {name:"Your request was rejected"})).toBeInTheDocument();
  }
  await waitFor(() => expect(screen.queryByText(success)).not.toBeInTheDocument());
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST")).toHaveLength(1);
}, 15000);
