import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { BulkReviewResult, ManagerActivity as ActivityData, ManagerOverview as OverviewData, WorkflowRequest } from "../../api/types";
import { ManagerActivity } from "./ManagerActivity";
import { ManagerBulkReview } from "./ManagerBulkReview";
import { ManagerOverview } from "./ManagerOverview";
import { useBulkReview, useManagerActivity, useManagerOverview } from "./useManagerWorkspace";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
const identity = vi.hoisted(() => ({ id: "manager.demo", role: "manager" }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test", user: identity }) }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => {
  vi.clearAllMocks();
  identity.id = "manager.demo"; identity.role = "manager";
});

const overview: OverviewData = {
  summary: { new: 7, in_review: 4, needs_attention: 3, overdue: 2, waiting_for_employee: 5, awaiting_completion: 1, completed_last_30_days: 8 },
  policy: { review_days: 5, description: "The review target is five calendar days; waiting for the employee is excluded." },
};
function request(overrides: Partial<WorkflowRequest> = {}): WorkflowRequest {
  return { id: "r1", number: 1, title: "Request one", type: "document", type_label: "Document", priority: "normal", status: "submitted", applicant: "employee.demo", approver: "manager.demo", revision: 3, review_round: 1, start_date: null, end_date: null, duration_days: null, comment: "Relevant request facts", created_at: "2030-01-01T12:00:00Z", updated_at: "2030-01-01T12:00:00Z", ...overrides };
}
function event(number = 1): ActivityData["events"][number] {
  return { id: `event-${number}`, request_id: `r${number}`, request_number: number, request_title: `Request ${number}`, event_type: "request_information", from_status: "in_review", to_status: "needs_information", actor: "manager.demo", details: { comment: `Question for request ${number}` }, created_at: "2030-01-01T12:00:00Z" };
}
function client() { return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); }
function mount(ui: ReactNode) {
  const cache = client();
  const view = render(<QueryClientProvider client={cache}>{ui}</QueryClientProvider>);
  return { cache, rerender: (next: ReactNode) => view.rerender(<QueryClientProvider client={cache}>{next}</QueryClientProvider>) };
}
function BulkHarness({ rows, scope = "new", enabled = true, onReload = () => {}, onOpenRequest = () => {}, onReviewQueue }: { rows: WorkflowRequest[]; scope?: string; enabled?: boolean; onReload?: () => void; onOpenRequest?: (id: string) => void; onReviewQueue?: () => void }) {
  const state = useBulkReview(rows, scope, enabled);
  return <>
    <ManagerBulkReview state={state} disabled={false} onReload={onReload} onOpenRequest={onOpenRequest} onReviewQueue={onReviewQueue}/>
    <output aria-label="Selected requests">{state.selected.map(item => item.id).join(",")}</output>
    <output aria-label="Eligible requests">{state.eligible.map(item => item.id).join(",")}</output>
    {rows.map(row => <button key={row.id} onClick={() => state.toggle(row)}>Toggle {row.id}</button>)}
  </>;
}
function selectAll() {
  fireEvent.click(screen.getByRole("button", { name: "Select requests" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select new requests on this page" }));
}

it("loads only the Manager overview and turns indicators into explicit queue filters", async () => {
  vi.mocked(api).mockResolvedValue(overview as never);
  const onFocus = vi.fn();
  mount(<ManagerOverview onFocus={onFocus}/>);
  fireEvent.click(await screen.findByRole("button", { name: "New requests: 7. Show requests" }));
  fireEvent.click(screen.getByRole("button", { name: "Under review: 4. Show requests" }));
  fireEvent.click(screen.getByRole("button", { name: "Needs attention: 3. Show requests" }));
  fireEvent.click(screen.getByRole("button", { name: "Overdue reviews: 2. Show requests" }));
  expect(onFocus.mock.calls.map(([value]) => value)).toEqual([{ status: "submitted" }, { status: "in_review" }, { status: "", attention: "needs_attention" }, { status: "", attention: "overdue" }]);
  expect(vi.mocked(api)).toHaveBeenCalledWith("/api/v1/manager/overview", "test");
  expect(screen.getByText(/Currently assigned to you/)).toHaveTextContent("Completed in the last 30 days: 8");
  fireEvent.click(screen.getByText("Queue details and review targets", { selector: "summary" }));
  expect(screen.getByText(overview.policy.description)).toBeVisible();
});

it("shows retry instead of stale or zero indicators when the overview refresh fails", async () => {
  vi.mocked(api).mockResolvedValue(overview as never);
  const { cache } = mount(<ManagerOverview onFocus={vi.fn()}/>);
  await screen.findByRole("button", { name: "New requests: 7. Show requests" });
  vi.mocked(api).mockRejectedValue(new Error("Offline"));
  await act(() => cache.invalidateQueries({ queryKey: ["manager-overview"] }));
  expect(await screen.findByRole("alert")).toHaveTextContent("still work with the request list");
  expect(screen.queryByRole("button", { name: /New requests:/ })).not.toBeInTheDocument();
  vi.mocked(api).mockResolvedValue(overview as never);
  fireEvent.click(screen.getByRole("button", { name: "Retry indicators" }));
  expect(await screen.findByRole("button", { name: "New requests: 7. Show requests" })).toBeInTheDocument();
});

it("loads activity only when opened, paginates on the server and opens the exact request", async () => {
  vi.mocked(api).mockImplementation(async path => ({ events: path.endsWith("offset=20") ? [event(21)] : Array.from({ length: 20 }, (_, index) => event(index + 1)), total: 21 }) as never);
  const onOpenChange = vi.fn(), onOpenRequest = vi.fn();
  const { rerender } = mount(<ManagerActivity open={false} onOpenChange={onOpenChange} onOpenRequest={onOpenRequest}/>);
  expect(vi.mocked(api)).not.toHaveBeenCalled();
  rerender(<ManagerActivity open onOpenChange={onOpenChange} onOpenRequest={onOpenRequest}/>);
  await screen.findByRole("button", { name: "REQ-000001 · Request 1" });
  expect(vi.mocked(api)).toHaveBeenCalledWith("/api/v1/manager/activity?limit=20&offset=0", "test");
  expect(screen.getByRole("button", { name: "Previous activity" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next activity" }));
  fireEvent.click(await screen.findByRole("button", { name: "REQ-000021 · Request 21" }));
  expect(vi.mocked(api)).toHaveBeenCalledWith("/api/v1/manager/activity?limit=20&offset=20", "test");
  expect(onOpenChange).toHaveBeenLastCalledWith(false);
  expect(onOpenRequest).toHaveBeenCalledWith("r21");
  expect(screen.getByRole("button", { name: "Next activity" })).toBeDisabled();
});

it("hides cached activity details when access is denied during refresh", async () => {
  vi.mocked(api).mockResolvedValue({ events: [event()], total: 1 } as never);
  const { cache } = mount(<ManagerActivity open onOpenChange={vi.fn()} onOpenRequest={vi.fn()}/>);
  await screen.findByRole("button", { name: "REQ-000001 · Request 1" });
  vi.mocked(api).mockRejectedValue(Object.assign(new Error("Not available"), { status: 403 }));
  await act(() => cache.invalidateQueries({ queryKey: ["manager-activity"] }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Activity could not be loaded");
  expect(screen.queryByText("Question for request 1")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "REQ-000001 · Request 1" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Activity pages" })).not.toBeInTheDocument();
});

it("selects only submitted requests assigned to this Manager, excluding own or foreign requests", () => {
  const rows = [request(), request({ id: "reviewed", status: "in_review" }), request({ id: "own", applicant: "manager.demo" }), request({ id: "foreign", approver: "other.manager" })];
  mount(<BulkHarness rows={rows}/>);
  expect(screen.getByLabelText("Eligible requests")).toHaveTextContent(/^r1$/);
  for (const id of ["reviewed", "own", "foreign"]) fireEvent.click(screen.getByRole("button", { name: `Toggle ${id}` }));
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  selectAll();
  expect(screen.getByLabelText("Selected requests")).toHaveTextContent(/^r1$/);
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});

it("clears selection and closes confirmation when filters change", () => {
  const rows = [request()];
  const { rerender } = mount(<BulkHarness rows={rows}/>);
  selectAll();
  fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  expect(screen.getByRole("dialog", { name: "Start review of 1 requests?" })).toBeInTheDocument();
  rerender(<BulkHarness rows={rows} scope="urgent"/>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  expect(screen.getByRole("button", { name: "Select requests" })).toBeInTheDocument();
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});

it("invalidates a selection when its revision or assignment changes instead of silently using new data", () => {
  const { rerender } = mount(<BulkHarness rows={[request()]}/>);
  selectAll();
  fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  rerender(<BulkHarness rows={[request({ revision: 4 })]}/>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Some selected requests changed");
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  fireEvent.click(screen.getByRole("button", { name: "Toggle r1" }));
  expect(screen.getByLabelText("Selected requests")).toHaveTextContent("r1");
  rerender(<BulkHarness rows={[request({ revision: 4, approver: "other.manager" })]}/>);
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});

it("requires confirmation, sends reviewed revisions and reports partial success without retrying successful items", async () => {
  const rows = [request(), request({ id: "r2", number: 2, title: "Request two", revision: 9 })];
  vi.mocked(api).mockResolvedValue({ results: [{ id: "r1", success: true, request: request({ status: "in_review", revision: 4 }) }, { id: "r2", success: false, error: "The request changed. Reload it." }] } as never);
  const onOpenRequest = vi.fn();
  mount(<BulkHarness rows={rows} onOpenRequest={onOpenRequest}/>);
  selectAll();
  fireEvent.click(screen.getByRole("button", { name: "Start review (2)" }));
  const confirmation = screen.getByRole("dialog", { name: "Start review of 2 requests?" });
  expect(confirmation).toHaveTextContent("does not approve, reject or reassign");
  expect(vi.mocked(api)).not.toHaveBeenCalled();
  fireEvent.click(within(confirmation).getByRole("button", { name: "Keep selecting" }));
  expect(screen.getByLabelText("Selected requests")).toHaveTextContent("r1,r2");
  fireEvent.click(screen.getByRole("button", { name: "Start review (2)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  expect(await screen.findByText("1 started · 1 not changed.")).toBeInTheDocument();
  expect(screen.getByText(/REQ-000002: The request changed/)).toBeInTheDocument();
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
  const [path, token, options] = vi.mocked(api).mock.calls[0];
  expect(path).toBe("/api/v1/manager/bulk-start-review"); expect(token).toBe("test");
  expect(JSON.parse(String(options?.body))).toEqual({ items: [{ id: "r1", expected_revision: 3 }, { id: "r2", expected_revision: 9 }] });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  fireEvent.click(screen.getByRole("button", { name: "Open started request" }));
  expect(onOpenRequest).toHaveBeenCalledWith("r1");
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
});

it("clears an uncertain network result and refreshes queue data before a new selection", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Network interrupted after the request was sent"));
  const onReload = vi.fn();
  const { cache } = mount(<BulkHarness rows={[request()]} onReload={onReload}/>);
  const invalidate = vi.spyOn(cache, "invalidateQueries");
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("result could not be confirmed");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  expect(screen.queryByText(/started ·/)).not.toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["manager-requests"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["manager-overview"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["manager-activity"] });
  fireEvent.click(screen.getByRole("button", { name: "Reload queue" }));
  expect(onReload).toHaveBeenCalledOnce();
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
});

it("identifies every processed and unchanged request in a mixed bulk result without retrying", async () => {
  const rows = [request(), request({ id: "r2", number: 2, title: "Request two" }), request({ id: "r3", number: 3, title: "Request three" }), request({ id: "r4", number: 4, title: "Request four" })];
  const onReviewQueue = vi.fn();
  vi.mocked(api).mockResolvedValue({ results: [
    { id: "r4", success: false, error: "This request was reassigned. Reload your queue." },
    { id: "r3", success: true, request: request({ id: "r3", title: "Do not use refreshed private content", status: "in_review" }) },
    { id: "r2", success: false, error: "The request changed. Reload it." },
    { id: "r1", success: true, request: request({ status: "in_review" }) },
  ] } as never);
  mount(<BulkHarness rows={rows} onReviewQueue={onReviewQueue}/>);
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (4)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  expect(await screen.findByText("2 started · 2 not changed.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const processed = screen.getByRole("list", { name: "Started requests" });
  expect(processed).toBeVisible();
  expect(within(processed).getAllByRole("listitem").map(item => item.textContent)).toEqual(["REQ-000003 · Request three", "REQ-000001 · Request one"]);
  const unchanged = screen.getByRole("list", { name: "Requests not changed" });
  expect(within(unchanged).getAllByRole("listitem").map(item => item.textContent)).toEqual(["REQ-000004: This request was reassigned. Reload your queue.", "REQ-000002: The request changed. Reload it."]);
  expect(screen.queryByText(/Do not use refreshed private content/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  expect(screen.queryByRole("button", { name: "Open started request" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View in-review queue" }));
  expect(onReviewQueue).toHaveBeenCalledOnce();
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
});

it("does not show an old Manager's pending outcome after switching accounts", async () => {
  let resolve!: (value: BulkReviewResult) => void;
  vi.mocked(api).mockImplementation(() => new Promise<BulkReviewResult>(done => { resolve = done; }) as never);
  const { rerender } = mount(<BulkHarness rows={[request()]}/>);
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledOnce());
  identity.id = "other.manager";
  rerender(<BulkHarness rows={[request({ id: "other-request", approver: "other.manager" })]}/>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  await act(async () => resolve({ results: [{ id: "r1", success: true, request: request({ status: "in_review" }) }] }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Select requests" })).toBeEnabled());
  expect(screen.queryByText(/started ·/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open started request" })).not.toBeInTheDocument();
});

it("does not retain an earlier success when a new bulk operation has an uncertain result", async () => {
  vi.mocked(api).mockResolvedValueOnce({ results: [{ id: "r1", success: true, request: request({ status: "in_review" }) }] } as never);
  const { rerender } = mount(<BulkHarness rows={[request()]}/>);
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  expect(await screen.findByText("1 started · 0 not changed.")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  rerender(<BulkHarness rows={[request({ id: "r2", number: 2, title: "Another request" })]}/>);
  vi.mocked(api).mockRejectedValueOnce(new Error("Connection lost after sending"));
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("result could not be confirmed");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.queryByText(/started ·/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open started request" })).not.toBeInTheDocument();
  expect(vi.mocked(api)).toHaveBeenCalledTimes(2);
});

it("does not fetch Manager data or allow bulk selection for Employee", async () => {
  identity.role = "employee"; identity.id = "employee.demo";
  const cache = client(), rows = [request({ approver: "employee.demo", applicant: "someone.else" })];
  const { result } = renderHook(() => ({ overview: useManagerOverview(), activity: useManagerActivity(true, 0), bulk: useBulkReview(rows, "all", true) }), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider> });
  act(() => { result.current.bulk.toggle(rows[0]); result.current.bulk.selectAll(); result.current.bulk.start(); });
  expect(result.current.bulk.eligible).toEqual([]);
  expect(result.current.bulk.selected).toEqual([]);
  expect(result.current.overview.fetchStatus).toBe("idle");
  expect(result.current.activity.fetchStatus).toBe("idle");
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});

it("caps bulk selection at twenty requests and sends only their reviewed revisions", async () => {
  const rows = Array.from({ length: 24 }, (_, index) => request({ id: `r${index + 1}`, number: index + 1, revision: index + 3 }));
  const cache = client();
  vi.mocked(api).mockResolvedValue({ results: [] } as never);
  const { result } = renderHook(() => useBulkReview(rows, "all", true), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider> });
  act(() => result.current.selectAll());
  expect(result.current.selected).toHaveLength(20);
  act(() => result.current.toggle(rows[23]));
  expect(result.current.selected.map(item => item.id)).not.toContain("r24");
  act(() => result.current.start());
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledOnce());
  expect(JSON.parse(String(vi.mocked(api).mock.calls[0][2]?.body)).items).toEqual(rows.slice(0, 20).map(item => ({ id: item.id, expected_revision: item.revision })));
});

it("does not publish a pending result into a different filter scope", async () => {
  let resolve!: (value: BulkReviewResult) => void;
  vi.mocked(api).mockImplementation(() => new Promise<BulkReviewResult>(done => { resolve = done; }) as never);
  const { rerender } = mount(<BulkHarness rows={[request()]}/>);
  selectAll(); fireEvent.click(screen.getByRole("button", { name: "Start review (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "Start selected reviews" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledOnce());
  rerender(<BulkHarness rows={[request({ id: "r2", number: 2 })]} scope="high-priority"/>);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await act(async () => resolve({ results: [{ id: "r1", success: true, request: request({ status: "in_review" }) }] }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Select requests" })).toBeEnabled());
  expect(screen.getByLabelText("Selected requests")).toBeEmptyDOMElement();
  expect(screen.queryByText(/started ·/)).not.toBeInTheDocument();
});
