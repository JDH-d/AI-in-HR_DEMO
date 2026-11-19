import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, login } from "../api/client";
import { App } from "./App";
import { AppProviders } from "./providers";

vi.mock("../api/client", () => ({ api: vi.fn(), login: vi.fn() }));
vi.mock("../features/requests/RequestDetailDrawer", () => ({ RequestDetailDrawer: ({ id }: { id: string | null }) => id ? <p>Opened request {id}</p> : null, requestNumber: (value: number) => String(value) }));
afterEach(cleanup);
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async path => path.includes("request-options") ? { categories: {}, statuses: [], priorities: [] } as never : { requests: [], counts: {}, total: 0 } as never);
});

it.each(["employee", "manager"] as const)("keeps a request link through login as %s", async role => {
  vi.mocked(login).mockResolvedValue({ token: "token", user: { id: role + ".demo", username: role, display_name: role, role } });
  render(<MemoryRouter initialEntries={["/requests?request=request-from-notification"]}><AppProviders><App/></AppProviders></MemoryRouter>);
  const button = role === "manager" ? /Manager/ : /Employee/;
  fireEvent.click(await screen.findByRole("button", { name: button }));
  fireEvent.change(screen.getByLabelText("Demo password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByText("Opened request request-from-notification")).toBeInTheDocument());
  expect(screen.getByRole("heading", { name: role === "manager" ? "Review queue" : "My requests" })).toBeInTheDocument();
});
