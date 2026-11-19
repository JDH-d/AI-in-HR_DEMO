import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { IntegrationsSection } from "./IntegrationsSection";
import type { Integrations } from "./useIntegrations";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test-token", user: { role: "knowledge_admin" } }) }));
afterEach(cleanup);
let state: Integrations;
beforeEach(() => {
  vi.clearAllMocks();
  state = { app_url: "https://peopleflow.example.test", items: [
    { provider: "slack", enabled: false, configured: true, revision: 0, pending: 0, configuration_error: "", last_delivery: null, active_delivery: null, recipients: {employee: true, manager: true} },
    { provider: "discord", enabled: false, configured: false, revision: 0, pending: 0, configuration_error: "Configure the bot on the server.", last_delivery: null, active_delivery: null, recipients: {employee: true, manager: true} },
  ] };
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    const item = state.items.find(item => path.includes(`/${item.provider}`));
    if (options?.method === "PATCH" && item) { const payload = JSON.parse(String(options.body)); item.enabled = payload.enabled; item.revision++; }
    if (options?.method === "POST" && item) { item.pending = 1; return { id: "test-job", status: "pending" } as never; }
    return structuredClone(state) as never;
  });
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><IntegrationsSection/></QueryClientProvider>);
  return client;
}

it("starts disabled and cannot test an unconfigured or disabled provider", async () => {
  mount();
  expect(await screen.findByRole("button", { name: "Send Slack test to Manager" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send Slack test to Manager" })).toHaveAccessibleDescription("Enable personal delivery to send a test.");
  expect(screen.getByRole("switch", { name: "Enable Discord notifications" })).toBeDisabled();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getAllByText("No notifications yet.")).toHaveLength(2);
});

it("enables one provider, queues a test explicitly, and shows delivery failure", async () => {
  const client = mount();
  fireEvent.click(await screen.findByRole("switch", { name: "Enable Slack notifications" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Send Slack test to Manager" })).toBeEnabled());
  const patch = vi.mocked(api).mock.calls.find(call => call[2]?.method === "PATCH")!;
  expect(JSON.parse(String(patch[2]?.body))).toEqual({ enabled: true, expected_revision: 0 });
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Send Slack test to Manager" }));
  expect(await screen.findByText(/Test notification accepted/)).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.find(call => call[2]?.method === "POST")?.[0]).toBe("/api/v1/admin/integrations/slack/test");
  expect(JSON.parse(String(vi.mocked(api).mock.calls.find(call => call[2]?.method === "POST")?.[2]?.body))).toEqual({audience: "manager"});
  state.items[0].pending = 0;
  state.items[0].last_delivery = { id: "test-job", status: "failed", attempts: 5, error: "The provider timed out.", updated_at: 1000, next_attempt_at: 0 };
  await client.invalidateQueries({ queryKey: ["integrations"] });
  expect(await screen.findByText("The provider timed out.")).toBeInTheDocument();
  expect(screen.getByText(/Last notification: failed/)).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Enable Discord notifications" })).toHaveAttribute("aria-checked", "false");
}, 15000);

it("offers retry on load errors without exposing settings", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("Unavailable"));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load integrations.");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Request notifications")).toBeInTheDocument();
});

it("cannot test an unlinked recipient and sends only the explicitly selected audience", async () => {
  state.items[0].enabled = true;
  state.items[0].recipients.manager = false;
  mount();
  expect(await screen.findByRole("button", { name: "Send Slack test to Manager" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send Slack test to Manager" })).toHaveAccessibleDescription("Connect the Manager account in Personal notifications.");
  fireEvent.click(screen.getByRole("button", { name: "Send Slack test to Employee" }));
  expect(await screen.findByText(/Test notification accepted for Employee/)).toBeInTheDocument();
  const posted = vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST");
  expect(posted).toHaveLength(1);
  expect(JSON.parse(String(posted[0][2]?.body))).toEqual({audience: "employee"});
});

it("does not report a completed test as waiting when a newer notification arrives", async () => {
  state.items[0].enabled = true;
  const client = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Send Slack test to Manager" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(true));
  state.items[0].pending = 0;
  state.items[0].last_delivery = { id: "test-job", status: "delivered", attempts: 1, error: "", updated_at: 1000, next_attempt_at: 0 };
  await client.invalidateQueries({ queryKey: ["integrations"] });
  expect(await screen.findByText(/Last notification: delivered/)).toBeInTheDocument();
  state.items[0].last_delivery = { ...state.items[0].last_delivery, id: "later-request-event", attempts: 2 };
  await client.invalidateQueries({ queryKey: ["integrations"] });
  await waitFor(() => expect(screen.getByText(/Attempts: 2/)).toBeInTheDocument());
  expect(screen.queryByText(/Waiting for delivery confirmation/)).not.toBeInTheDocument();
});

it("shows missing configuration instead of enabled and still allows disabling", async () => {
  state.items[0].enabled = true;
  state.items[0].configured = false;
  state.items[0].configuration_error = "Bot removed from server environment.";
  mount();
  expect(await screen.findByText("Needs configuration")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send Slack test to Manager" })).toBeDisabled();
  fireEvent.click(screen.getByRole("switch", { name: "Enable Slack notifications" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Enable Slack notifications" })).toHaveAttribute("aria-checked", "false"));
});

it("shows the active retry error even if the newest message has not been attempted", async () => {
  state.items[0].enabled = true;
  state.items[0].pending = 2;
  state.items[0].last_delivery = { id: "newer", status: "pending", attempts: 0, error: "", updated_at: 1001, next_attempt_at: 0 };
  Object.assign(state.items[0], { active_delivery: { id: "retrying", status: "pending", attempts: 1, error: "The provider requested a pause before retrying.", updated_at: 1000, next_attempt_at: 1035 } });
  mount();
  expect(await screen.findByText("The provider requested a pause before retrying.")).toBeInTheDocument();
  expect(screen.getByText(/Current notification: pending/)).toBeInTheDocument();
  expect(screen.getByText(/Retry no earlier than/)).toBeInTheDocument();
});

it.each(["Slack", "Discord"])("toggles %s independently and posts a test only on explicit click", async name => {
  state.items.forEach(item => { item.configured = true; });
  mount();
  const toggle = await screen.findByRole("switch", { name: `Enable ${name} notifications` });
  const other = screen.getByRole("switch", { name: `Enable ${name === "Slack" ? "Discord" : "Slack"} notifications` });
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  expect(other).toHaveAttribute("aria-checked", "false");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: `Send ${name} test to Manager` }));
  expect(await screen.findByText(/Test notification accepted/)).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST").map(call => call[0])).toEqual([`/api/v1/admin/integrations/${name.toLowerCase()}/test`]);
  await waitFor(() => expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
  expect(screen.getByRole("button", { name: `Send ${name} test to Manager` })).toBeDisabled();
  expect(other).toHaveAttribute("aria-checked", "false");
});
