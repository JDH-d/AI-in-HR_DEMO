import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { EmployeeHome } from "./EmployeeHome";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "synthetic", user: { id: "employee.test", role: "employee", display_name: "Test employee" } }) }));
vi.mock("../../components/Shell", () => ({ Shell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("../requests/RequestDrawer", () => ({ RequestDrawer: ({ open }: { open: boolean }) => open ? <div role="dialog" aria-label="Create request">Request steps</div> : null }));
vi.mock("../integrations/PersonalNotifications", () => ({ PersonalNotifications: ({ open }: { open: boolean }) => open ? <div role="dialog" aria-label="Personal notifications">Connection settings</div> : null }));
vi.mock("./EmployeeHelp", () => ({ EmployeeHelp: ({ open }: { open: boolean }) => open ? <div role="dialog" aria-label="Employee help">Help content</div> : null }));

const request = { id: "request-owned", number: 8, title: "Workplace letter", type_label: "Document", status: "needs_information", updated_at: "2030-01-01T10:00:00Z" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async path => {
    if (path.includes("conversations")) return { conversations: [{ id: "saved-chat", title: "My onboarding questions", updated_at: "2030-01-01T10:00:00Z" }], has_more: false } as never;
    const status = new URL(path, "http://localhost").searchParams.get("status");
    return { requests: status === "draft" ? [{ ...request, id: "draft-owned", number: 9, status: "draft", title: "Private draft" }] : [request], total: 1, counts: { needs_information: 4, draft: 1, in_review: 2 } } as never;
  });
});
afterEach(cleanup);
function mount(cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  render(<MemoryRouter><QueryClientProvider client={cache}><EmployeeHome/></QueryClientProvider></MemoryRouter>);
  return cache;
}

it("shows actionable owner-scoped tasks and exact links, with totals independent of the preview size", async () => {
  mount();
  expect(await screen.findByRole("link", { name: "Reply REQ-000008: Workplace letter" })).toHaveAttribute("href", "/requests?request=request-owned");
  expect(screen.getByRole("link", { name: "Continue draft REQ-000009: Private draft" })).toHaveAttribute("href", "/requests?request=draft-owned");
  expect(within(screen.getByRole("navigation", { name: "Your request summary" })).getByRole("link", { name: /Needs your reply: 4/ })).toHaveAttribute("href", "/requests?status=needs_information");
  expect(vi.mocked(api).mock.calls.every(([, token]) => token === "synthetic")).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("status=needs_information"))).toBe(true);
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.includes("/requests?")).every(([path]) => new URL(path,"http://localhost").searchParams.get("status") !== "")).toBe(true);
});

it("opens request creation, personal notifications and help without making a write request", async () => {
  mount();
  await screen.findByRole("link", { name: /Reply REQ/ });
  fireEvent.click(screen.getByRole("button", { name: "Create request" }));
  expect(screen.getByRole("dialog", { name: "Create request" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Manage notifications" }));
  expect(screen.getByRole("dialog", { name: "Personal notifications" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open employee help" }));
  expect(screen.getByRole("dialog", { name: "Employee help" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.every(([, , options]) => !options?.method)).toBe(true);
});

it("links to the saved conversation instead of creating another one", async () => {
  mount();
  expect(await screen.findByRole("link", { name: /My onboarding questions/ })).toHaveAttribute("href", "/employee?conversation=saved-chat");
});

it("keeps the home preview separate from the infinite chat search cache for the word home", async () => {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const searchKey = ["conversations", "employee.test", "home"];
  const searchResults = { pages: [{ conversations: [{ id: "search-only", title: "Home office policy", updated_at: "2030-01-01T09:00:00Z" }], has_more: false }], pageParams: [0] };
  cache.setQueryData(searchKey, searchResults);

  mount(cache);
  expect(await screen.findByRole("link", { name: /My onboarding questions/ })).toHaveAttribute("href", "/employee?conversation=saved-chat");
  expect(screen.queryByRole("link", { name: /Home office policy/ })).not.toBeInTheDocument();
  expect(cache.getQueryData(searchKey)).toEqual(searchResults);
  expect(cache.getQueryCache().findAll({ queryKey: ["conversations", "employee.test"] })).toHaveLength(2);
  expect(vi.mocked(api).mock.calls.some(([path]) => path === "/api/v1/conversations?limit=3&offset=0")).toBe(true);
});

it("explains empty tasks, drafts, requests and conversations", async () => {
  vi.mocked(api).mockImplementation(async path => (path.includes("conversations") ? { conversations: [], has_more: false } : { requests: [], total: 0, counts: {} }) as never);
  mount();
  expect(await screen.findByText(/No replies needed/)).toBeInTheDocument();
  expect(screen.getByText(/No saved drafts/)).toBeInTheDocument();
  expect(screen.getByText(/No chats yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start your first request" })).toBeInTheDocument();
});

it("does not mistake failed loading for empty tasks and recovers with Retry", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Offline"));
  mount();
  await screen.findAllByRole("alert");
  expect(screen.queryByText(/No replies needed/)).not.toBeInTheDocument();
  expect(screen.queryByText(/No saved drafts/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start your first request" })).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Your request summary" })).toHaveTextContent("—");
  vi.mocked(api).mockResolvedValue({ requests: [request], total: 1, counts: { needs_information: 1 } } as never);
  fireEvent.click(within(screen.getAllByRole("alert")[0]).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByRole("link", { name: /Reply REQ/ })).toBeInTheDocument());
});
