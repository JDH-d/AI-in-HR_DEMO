import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { LoginPage } from "./LoginPage";

const auth = vi.hoisted(() => ({user: null, login: vi.fn()}));
vi.mock("../app/providers", () => ({useAuth: () => auth}));
beforeEach(() => { auth.login.mockReset(); });
afterEach(cleanup);

function setup() { render(<MemoryRouter><LoginPage/></MemoryRouter>); }

it.each([
  [/^Employee/, "employee"],
  [/^Manager/, "manager"],
  [/^Knowledge Admin/, "knowledge_admin"],
] as const)("fills the username when choosing %s", (name, username) => {
  setup();
  fireEvent.click(screen.getByRole("button", {name}));
  expect(screen.getByLabelText("Username")).toHaveValue(username);
  expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
  expect(screen.getByRole("button", {name})).toHaveAttribute("aria-pressed", "true");
  expect(auth.login).not.toHaveBeenCalled();
});

it("submits the manually entered username and updates the workspace hint", async () => {
  auth.login.mockResolvedValue(undefined);
  setup();
  fireEvent.change(screen.getByLabelText("Username"), {target: {value: "  MANAGER  "}});
  expect(screen.getByRole("heading", {name: "Sign in as Manager"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: /^Manager/})).toHaveAttribute("aria-pressed", "true");
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "demo-test-password"}});
  fireEvent.submit(screen.getByLabelText("Username").closest("form")!);
  await waitFor(() => expect(auth.login).toHaveBeenCalledWith("manager", "demo-test-password"));
});

it("rejects an empty username locally and focuses it without sending a request", () => {
  setup();
  fireEvent.change(screen.getByLabelText("Username"), {target: {value: "   "}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  expect(auth.login).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter your demo username or choose a workspace");
  expect(screen.getByLabelText("Username")).toHaveFocus();
  expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Demo password")).toHaveAttribute("aria-invalid", "false");
});

it("never substitutes a selected role for an unknown username", async () => {
  auth.login.mockRejectedValue(new ApiError(422, "Internal validation details"));
  setup();
  fireEvent.click(screen.getByRole("button", {name: /^Knowledge Admin/}));
  fireEvent.change(screen.getByLabelText("Username"), {target: {value: "unknown.account"}});
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "demo-test-password"}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  await waitFor(() => expect(auth.login).toHaveBeenCalledWith("unknown.account", "demo-test-password"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Check your demo username and password");
  expect(screen.getByLabelText("Username")).toHaveValue("unknown.account");
  expect(screen.getByLabelText("Demo password")).toHaveValue("demo-test-password");
  expect(screen.getByRole("button", {name: /^Knowledge Admin/})).toHaveAttribute("aria-pressed", "false");
  fireEvent.change(screen.getByLabelText("Username"), {target: {value: "employee"}});
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("explains an empty password locally and focuses the field without sending a request", () => {
  setup();
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  expect(auth.login).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("Enter the demo password to continue.");
  expect(screen.getByLabelText("Demo password")).toHaveFocus();
});

it("keeps the chosen demo role and password when authentication fails", async () => {
  auth.login.mockRejectedValue(new ApiError(401, "Unauthorized"));
  setup();
  fireEvent.click(screen.getByRole("button", {name: /^Manager/}));
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "demo-test-password"}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  await waitFor(() => expect(auth.login).toHaveBeenCalledWith("manager", "demo-test-password"));
  expect(await screen.findByRole("alert")).toHaveTextContent("That username or password wasn't accepted.");
  expect(screen.getByLabelText("Demo password")).toHaveValue("demo-test-password");
  expect(screen.getByRole("button", {name: /^Manager/})).toHaveAttribute("aria-pressed", "true");
});

it("provides a useful recovery instruction without exposing backend validation messages", async () => {
  auth.login.mockRejectedValue(new ApiError(422, "String should have at least 1 character"));
  setup();
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "invalid"}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  const alert = await screen.findByRole("alert");
  expect(alert).not.toHaveTextContent("String should");
  expect(alert).toHaveTextContent("Check your demo username and password, then try again.");
});

it("explains how to recover when the server cannot be reached", async () => {
  auth.login.mockRejectedValue(new TypeError("Failed to fetch"));
  setup();
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "test"}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Check that the application is running");
});

it("explains the sign-in cooldown and preserves the entered credentials", async () => {
  auth.login.mockRejectedValue(new ApiError(429, "Too many attempts"));
  setup();
  fireEvent.change(screen.getByLabelText("Demo password"), {target: {value: "synthetic-password"}});
  fireEvent.click(screen.getByRole("button", {name: "Continue"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Wait one minute, then try again.");
  expect(screen.getByLabelText("Demo password")).toHaveValue("synthetic-password");
  expect(screen.getByRole("button", {name: "Continue"})).toBeEnabled();
});
