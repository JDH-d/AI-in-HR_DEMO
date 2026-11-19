import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { login } from "../api/client";
import { App } from "./App";
import { AppProviders } from "./providers";

vi.mock("../api/client", () => ({ login: vi.fn() }));
vi.mock("../features/chat/ChatPage", () => ({ ChatPage: () => <h1>Saved employee chat</h1> }));
vi.mock("../features/employee/EmployeeHome", () => ({ EmployeeHome: () => <h1>Employee tasks</h1> }));
vi.mock("../features/manager/ManagerPage", () => ({ ManagerPage: () => <h1>Manager queue</h1> }));
vi.mock("../features/knowledge-base/KnowledgePage", () => ({ KnowledgePage: () => <h1>Knowledge administration</h1> }));
function Location() { const location = useLocation(); return <output aria-label="Current route">{location.pathname + location.search + location.hash}</output>; }
beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(login).mockResolvedValue({ token: "synthetic", user: { id: "employee.test", username: "employee.test", display_name: "Employee", role: "employee" } });
});
afterEach(() => { cleanup(); sessionStorage.clear(); });
async function signIn(path: string) {
  render(<MemoryRouter initialEntries={[path]}><AppProviders><App/><Location/></AppProviders></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("Demo password"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}
it("lands a new employee sign-in on the task homepage", async () => {
  await signIn("/login");
  expect(await screen.findByRole("heading", { name: "Employee tasks" })).toBeInTheDocument();
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/home");
});
it.each([
  ["manager", "/manager", "Manager queue"],
  ["knowledge_admin", "/knowledge", "Knowledge administration"],
] as const)("opens the server-confirmed %s workspace rather than trusting the account hint", async (role, path, heading) => {
  vi.mocked(login).mockResolvedValue({ token: "synthetic", user: { id: `${role}.test`, username: role, display_name: "Test account", role } });
  await signIn("/login");
  expect(login).toHaveBeenCalledWith("employee", "test-password");
  expect(await screen.findByRole("heading", {name: heading})).toBeInTheDocument();
  expect(screen.getByLabelText("Current route")).toHaveTextContent(path);
});
it.each(["/employee?conversation=saved-dialog#latest", "/chat?conversation=saved-dialog#latest"])("preserves saved conversation %s through sign-in", async path => {
  await signIn(path);
  expect(await screen.findByRole("heading", { name: "Saved employee chat" })).toBeInTheDocument();
  expect(screen.getByLabelText("Current route")).toHaveTextContent("/employee?conversation=saved-dialog#latest");
});
