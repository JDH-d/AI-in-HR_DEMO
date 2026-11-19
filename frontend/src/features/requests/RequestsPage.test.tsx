import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { RequestsPage } from "./RequestsPage";

const auth = vi.hoisted(() => ({ role: "manager" }));
vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test", user: { id: `${auth.role}.demo`, role: auth.role } }) }));
vi.mock("../../components/Shell", () => ({ Shell: ({ children, headerContent }: { children: React.ReactNode; headerContent?: React.ReactNode }) => <main>{headerContent}{children}</main> }));
vi.mock("./RequestDrawer", () => ({ RequestDrawer: ({open,onOpenChange,onOpenRequest}: {open:boolean;onOpenChange:(value:boolean)=>void;onOpenRequest:(id:string)=>void}) => open ? <div role="dialog" aria-label="Create request"><button onClick={()=>onOpenChange(false)}>Close form</button><button onClick={()=>onOpenRequest("saved-request")}>Open saved request</button></div> : null }));
vi.mock("./RequestDetailDrawer", () => ({ RequestDetailDrawer: ({ id, presentation, onClose }: { id: string; presentation: string; onClose: () => void }) => <div><p>{presentation}: {id}</p><button onClick={onClose}>Back to requests</button></div>, requestNumber: (value: number) => `REQ-${String(value).padStart(6, "0")}` }));
afterEach(cleanup);
const rows = [{ id: "r1", number: 1, revision: 2, title: "A standard letter", priority: "normal", status: "submitted", type_label: "Document", applicant: "employee.demo", approver: "manager.demo", updated_at: "2030-01-01" }];
const overview = { summary: { new: 1, in_review: 3, waiting_for_employee: 2, awaiting_completion: 1, overdue: 2, needs_attention: 4, completed_last_30_days: 6 }, policy: { review_days: 5, description: "Review within five calendar days after submission or reply." } };
beforeEach(() => {
  auth.role = "manager";
  vi.clearAllMocks();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.mocked(api).mockImplementation(async path => path.includes("request-options") ? { statuses: ["draft", "submitted", "in_review", "needs_information", "approved"], categories: { document: "Document" }, priorities: ["normal", "high"], managers: [] } as never : path.includes("manager/overview") ? overview as never : { requests: rows, counts: { submitted: 1, in_review: 0, needs_information: 0 }, total: 21 } as never);
});
function Location() { return <output aria-label="Location">{useLocation().search}</output>; }
function mount(path = "/manager") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter initialEntries={[path]}><QueryClientProvider client={client}><RequestsPage/><Location/></QueryClientProvider></MemoryRouter>);
  return client;
}

it("defaults Manager to new work, filters on the server and excludes private drafts from options", async () => {
  mount();
  await screen.findByText("A standard letter");
  expect(screen.getByRole("button", { name: "Open REQ-000001: A standard letter" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("status=submitted"))).toBe(true);
  expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Filters" }));
  expect(within(screen.getByLabelText("Status")).queryByRole("option", { name: "Draft" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /In review/ }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("status=in_review"))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "All requests" }));
  await waitFor(() => expect(screen.getByLabelText("Status")).toHaveValue(""));
  expect(screen.getByLabelText("Location")).toHaveTextContent("status=all");
});

it("keeps URL filters through a full-page detail and resets pagination when a filter changes", async () => {
  mount("/manager?status=all&category=document&offset=20");
  fireEvent.click(await screen.findByRole("button", { name: "Open REQ-000001: A standard letter" }));
  expect(screen.getByText("page: r1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Back to requests" }));
  expect(screen.getByLabelText("Location")).toHaveTextContent("category=document");
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "letter" } });
  await waitFor(() => expect(screen.getByLabelText("Location")).not.toHaveTextContent("offset=20"));
  expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("q=letter") && url.includes("offset=0"))).toBe(true);
});

it("shows a retryable error without pretending the queue is empty or showing zero counts", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Offline"));
  mount();
  expect(await screen.findByText(/Requests could not be refreshed/)).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /No .*requests/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
});

it("allows Employee to find private drafts and create a request", async () => {
  auth.role = "employee";
  mount("/requests");
  expect(await screen.findByRole("button", { name: "New request" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Filters" }));
  expect(await screen.findByRole("option", { name: "Draft" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Drafts/ }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("status=draft"))).toBe(true));
});

it("opens creation from employee help and removes the creation parameter when opening the saved request",async()=>{
  auth.role="employee";
  mount("/requests?new=1");
  expect(screen.getByRole("dialog",{name:"Create request"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Open saved request"}));
  expect(screen.getByText("page: saved-request")).toBeInTheDocument();
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("new=1");
});

it("ignores an employee creation link for Manager",()=>{
  mount("/manager?new=1");
  expect(screen.queryByRole("dialog",{name:"Create request"})).not.toBeInTheDocument();
});

it("returns to the nearest remaining page when processing shrinks a queue", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[0].includes("request-options")) return original(...args);
    const offset = new URL(args[0], "http://localhost").searchParams.get("offset");
    return { requests: offset === "20" ? [] : rows, counts: { submitted: 20 }, total: 20 } as never;
  });
  mount("/manager?offset=20");
  await screen.findByText("A standard letter");
  expect(screen.getByRole("button", { name: "Open REQ-000001: A standard letter" })).toBeInTheDocument();
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("offset=20");
  expect(screen.getByLabelText("Request pages")).toHaveTextContent("1–1 of 20");
  expect(screen.queryByRole("heading", { name: "No matching requests" })).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(([url]) => url.includes("/requests?"))).toHaveLength(2);
});

it("returns keyboard focus to the list heading when the processed row is no longer visible", async () => {
  const cache = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Open REQ-000001: A standard letter" }));
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => args[0].includes("request-options") ? original(...args) : { requests: [], counts: { submitted: 0 }, total: 0 } as never);
  await cache.invalidateQueries({ queryKey: ["manager-requests"] });
  fireEvent.click(screen.getByRole("button", { name: "Back to requests" }));
  await screen.findByRole("heading", { name: "No matching requests" });
  expect(screen.getByRole("heading", { name: "Review queue" })).toHaveFocus();
});

it("sorts through accessible table headers and exposes active advanced filters", async () => {
  mount("/manager?category=document&priority=high");
  await screen.findByRole("table", { name: "Requests assigned to you" });
  expect(screen.getByRole("button", { name: "Filters (2)" })).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(screen.getByRole("button", { name: "Priority" }));
  await waitFor(() => expect(screen.getByLabelText("Location")).toHaveTextContent("sort=priority"));
  expect(await screen.findByRole("columnheader", { name: "Priority" })).toHaveAttribute("aria-sort", "descending");
  fireEvent.click(screen.getByRole("button", { name: "Priority" }));
  await waitFor(() => expect(screen.getByRole("columnheader", { name: "Priority" })).toHaveAttribute("aria-sort", "ascending"));
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("category=");
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("priority=");
});

it("supports the compact view selector and keeps mobile sorting with the same server filters", async () => {
  mount("/manager?category=document&offset=20");
  await screen.findByRole("button", { name: "Open REQ-000001: A standard letter" });
  fireEvent.change(screen.getByLabelText("Request view"), { target: { value: "needs_information" } });
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("status=needs_information") && url.includes("category=document") && url.includes("offset=0"))).toBe(true));
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("offset=20");
  fireEvent.click(screen.getByRole("button", { name: "Filters (1)" }));
  fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "number" } });
  fireEvent.change(screen.getByLabelText("Order"), { target: { value: "asc" } });
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("sort=number") && url.includes("order=asc") && url.includes("status=needs_information"))).toBe(true));
  fireEvent.change(screen.getByLabelText("Status"), { target: { value: "approved" } });
  expect(screen.getByLabelText("Request view")).toHaveValue("approved");
  expect(within(screen.getByLabelText("Request view")).queryByRole("option", { name: "Drafts" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.getByLabelText("Location")).toHaveTextContent("status=approved");
  expect(screen.queryByLabelText("Sort by")).not.toBeInTheDocument();
});

it("opens overdue work from the overview without leaving old category or pagination filters active", async () => {
  mount("/manager?status=in_review&category=document&priority=high&offset=20&q=letter&assignee=manager.demo&sort=title&order=desc");
  fireEvent.click(await screen.findByRole("button", { name: "Overdue reviews: 2. Show requests" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("/requests?") && url.includes("attention=overdue") && !url.includes("category=") && !url.includes("status=") && url.includes("offset=0"))).toBe(true));
  expect(screen.getByLabelText("Location")).toHaveTextContent("status=all");
  for (const filter of ["priority", "q", "assignee", "sort", "order"]) expect(screen.getByLabelText("Location")).not.toHaveTextContent(`${filter}=`);
  fireEvent.click(screen.getByRole("button", { name: /In review/ }));
  expect(screen.getByLabelText("Location")).not.toHaveTextContent("attention=");
});

it("keeps whole-queue indicators independent of the filtered results", async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => args[0].includes("/requests?") ? { requests: [], counts: {}, total: 0 } as never : original(...args));
  mount("/manager?status=all&q=does-not-match&category=document");
  expect(await screen.findByRole("heading", { name: "No matching requests" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New requests: 1. Show requests" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Under review: 3. Show requests" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Needs attention: 4. Show requests" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Overdue reviews: 2. Show requests" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(([url]) => url.includes("/manager/overview")).map(([url]) => url)).toEqual(["/api/v1/manager/overview"]);
});

it("combines attention and assignee with the existing server filters and explains the permission boundary", async () => {
  mount("/manager?status=all&category=document");
  fireEvent.click(await screen.findByRole("button", { name: "Filters (1)" }));
  fireEvent.change(screen.getByLabelText("Assigned manager"), { target: { value: "manager.demo" } });
  fireEvent.change(screen.getByLabelText("Attention"), { target: { value: "needs_attention" } });
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("assignee=manager.demo") && url.includes("attention=needs_attention") && url.includes("category=document"))).toBe(true));
  expect(screen.getByText(/Filtering does not expand access/)).toBeInTheDocument();
});

it("keeps manager indicators, bulk actions and activity out of Employee requests", async () => {
  auth.role = "employee";
  mount("/requests");
  await screen.findByRole("button", { name: "Open REQ-000001: A standard letter" });
  expect(screen.queryByRole("region", { name: "Your queue overview" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Activity log" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Select requests" })).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(([url]) => url.includes("/manager/"))).toBe(false);
});
