import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Role, User } from "../api/types";
import { AppProviders, useAuth } from "./providers";

const loginRequest = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({ login: loginRequest }));

function Session({ role = "employee" }: { role?: Role }) {
  const auth = useAuth();
  return <>
    <output aria-label="Current account">{auth.user?.role ?? "signed out"}</output>
    <button onClick={() => void auth.login(role, "synthetic-password")}>Sign in</button>
    <button onClick={auth.logout}>Sign out</button>
  </>;
}

function setup(role?: Role) {
  return render(<AppProviders><Session role={role}/></AppProviders>);
}

function savedSession(role: Role = "employee") {
  const user: User = { id: role, username: `${role}.test`, display_name: "Test account", role };
  sessionStorage.setItem("pf_token", "current-test-token");
  sessionStorage.setItem("pf_user", JSON.stringify(user));
  return user;
}

beforeEach(() => { sessionStorage.clear(); loginRequest.mockReset(); });
afterEach(() => { cleanup(); sessionStorage.clear(); });

describe("authentication session", () => {
  it.each<Role>(["employee", "manager", "knowledge_admin"])(
    "preserves the %s login after remount and removes it on logout",
    async role => {
      const user: User = { id: role, username: `${role}.test`, display_name: "Test account", role };
      loginRequest.mockResolvedValue({ token: "synthetic-token", user });
      const first = setup(role);
      expect(screen.getByLabelText("Current account")).toHaveTextContent("signed out");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() => expect(screen.getByLabelText("Current account")).toHaveTextContent(role));
      expect(loginRequest).toHaveBeenCalledWith(role, "synthetic-password");
      first.unmount();

      setup(role);
      expect(screen.getByLabelText("Current account")).toHaveTextContent(role);
      fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
      expect(screen.getByLabelText("Current account")).toHaveTextContent("signed out");
      expect(sessionStorage.getItem("pf_token")).toBeNull();
      expect(sessionStorage.getItem("pf_user")).toBeNull();
    },
  );

  it("signs out when the current session expires", () => {
    savedSession();
    setup();
    act(() => window.dispatchEvent(new CustomEvent("auth-expired", { detail: "current-test-token" })));
    expect(screen.getByLabelText("Current account")).toHaveTextContent("signed out");
    expect(sessionStorage.getItem("pf_token")).toBeNull();
  });

  it("ignores a delayed authentication failure from an older session", () => {
    savedSession("manager");
    setup("manager");
    act(() => window.dispatchEvent(new CustomEvent("auth-expired", { detail: "old-test-token" })));
    expect(screen.getByLabelText("Current account")).toHaveTextContent("manager");
    expect(sessionStorage.getItem("pf_token")).toBe("current-test-token");
  });
});
