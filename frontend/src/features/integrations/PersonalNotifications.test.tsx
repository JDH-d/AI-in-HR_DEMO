import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { PersonalNotifications } from "./PersonalNotifications";
import type { PersonalIntegrations } from "./usePersonalNotifications";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
const auth = vi.hoisted(() => ({ token: "test-token", user: { id: "employee.demo", role: "employee", display_name: "Demo Employee" } }));
vi.mock("../../app/providers", () => ({ useAuth: () => auth }));
let state: PersonalIntegrations;
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(auth.user, { id: "employee.demo", role: "employee", display_name: "Demo Employee" });
  state = { items: [
    { provider: "slack", configured: true, enabled: true, connected: false, external_user_id: null, pending: null },
    { provider: "discord", configured: false, enabled: false, connected: false, external_user_id: null, pending: null },
  ] };
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (path.endsWith("/link-code")) return { code: "synthetic-code", command: "/peopleflow link synthetic-code", expires_at: Date.now() / 1000 + 600 } as never;
    if (path.endsWith("/confirm")) {
      state.items[0] = { ...state.items[0], connected: true, external_user_id: "U12345678", pending: null };
    }
    if (options?.method === "DELETE") state.items[0] = { ...state.items[0], connected: false, external_user_id: null, pending: null, connection_error: "" };
    if (path.endsWith("/test")) return { id: "test-job", status: "pending" } as never;
    return structuredClone(state) as never;
  });
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><PersonalNotifications/></QueryClientProvider>);
  return client;
}
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Personal notifications" }));
  await screen.findByRole("button", { name: "Connect Slack" });
}

it("loads connections only after opening and never offers a role switch", async () => {
  mount();
  expect(api).not.toHaveBeenCalled();
  await open();
  expect(screen.getByText(/Signed in as Demo Employee \(employee\)/)).toBeInTheDocument();
  expect(screen.getByText(/Approval, rejection and other status changes are not sent automatically/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connect Discord" })).toBeDisabled();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Manager$/ })).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.every(call => !call[2]?.method)).toBe(true);
});

it("requires explicit code generation and confirmation of the externally verified account", async () => {
  const client = mount();
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
  expect(await screen.findByRole("textbox", { name: "Slack connection command" })).toHaveValue("/peopleflow link synthetic-code");
  expect(screen.getByText("Link in bot")).toHaveAttribute("aria-current", "step");
  expect(screen.queryByRole("button", { name: "Confirm my Slack account" })).not.toBeInTheDocument();
  state.items[0].pending = { challenge_id: "challenge-id", external_user_id: "U12345678" };
  await client.invalidateQueries({ queryKey: ["personal-integrations", "employee.demo"] });
  expect(await screen.findByText("U12345678")).toBeInTheDocument();
  expect(screen.getByText("Confirm account")).toHaveAttribute("aria-current", "step");
  expect(screen.queryByRole("textbox", { name: "Slack connection command" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm my Slack account" }));
  expect(await screen.findByText("Connected account ID: U12345678")).toBeInTheDocument();
  const confirm = vi.mocked(api).mock.calls.find(call => call[0].endsWith("/confirm"))!;
  expect(JSON.parse(String(confirm[2]?.body))).toEqual({ challenge_id: "challenge-id" });
  expect(vi.mocked(api).mock.calls.some(call => call[0].endsWith("/test"))).toBe(false);
});

it("sends a personal test only on click and preserves the connection when disconnect is cancelled", async () => {
  state.items[0].connected = true;
  state.items[0].external_user_id = "U12345678";
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Personal notifications" }));
  const test = await screen.findByRole("button", { name: "Send Slack test to me" });
  expect(screen.queryByRole("button", { name: "Connect Slack" })).not.toBeInTheDocument();
  fireEvent.click(test);
  expect(await screen.findByText(/Slack test accepted for delivery to your personal account/)).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[0].endsWith("/test"))).toHaveLength(1);
  await waitFor(() => expect(screen.getByRole("button", { name: "Disconnect Slack" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Disconnect Slack" }));
  fireEvent.click(screen.getByRole("button", { name: "Keep connection" }));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Disconnect Slack" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect Slack" }));
  expect(await screen.findByRole("button", { name: "Connect Slack" })).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "DELETE")).toHaveLength(1);
});

it("shows recoverable connection errors and never auto-retries a mutation", async () => {
  mount();
  await open();
  vi.mocked(api).mockRejectedValueOnce(new Error("Connection code is no longer valid."));
  fireEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection code is no longer valid. Refresh connections and try again.");
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "POST")).toHaveLength(1);
});

it("recovers a stored connection after the bot workspace changes before offering another code", async () => {
  state.items[0].external_user_id = "UOLDWORKSPACE";
  state.items[0].connection_error = "Bot workspace/application changed. Disconnect and connect again.";
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Personal notifications" }));
  expect(await screen.findByText("Reconnect needed")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Bot workspace/application changed. Disconnect and connect again.");
  expect(screen.getByText("Previously connected account ID: UOLDWORKSPACE")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Connect Slack" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Send Slack test to me" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Disconnect Slack" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect Slack" }));
  const connect = await screen.findByRole("button", { name: "Connect Slack" });
  await waitFor(() => expect(connect).toBeEnabled());
  fireEvent.click(connect);
  expect(await screen.findByRole("textbox", { name: "Slack connection command" })).toHaveValue("/peopleflow link synthetic-code");
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes.map(call => [call[0], call[2]?.method])).toEqual([
    ["/api/v1/me/integrations/slack", "DELETE"],
    ["/api/v1/me/integrations/slack/link-code", "POST"],
  ]);
});

it("clears a displayed connection code when the drawer is closed", async () => {
  mount();
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
  await screen.findByRole("textbox", { name: "Slack connection command" });
  fireEvent.click(screen.getByRole("button", { name: "Close drawer" }));
  await open();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("hides expired codes and explains how to continue", async () => {
  mount();
  await open();
  vi.mocked(api).mockResolvedValueOnce({code: "expired", command: "/peopleflow link expired", expires_at: Date.now() / 1000 - 1} as never);
  fireEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
  expect(await screen.findByText("A connection code expired. Generate a new code to continue.")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "Slack connection command" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connect Slack" })).toBeEnabled();
});

it("shows manager-specific guidance without employee message content", async () => {
  Object.assign(auth.user, { id: "manager.demo", role: "manager", display_name: "Demo Manager" });
  mount();
  await open();
  expect(screen.getByText(/Personal employee chat conversations are not forwarded/)).toBeInTheDocument();
  expect(screen.getByText(/Signed in as Demo Manager \(manager\)/)).toBeInTheDocument();
});

it("does not offer personal account linking to Knowledge Admin", () => {
  auth.user.role = "knowledge_admin";
  mount();
  expect(screen.queryByRole("button", { name: "Personal notifications" })).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
});
