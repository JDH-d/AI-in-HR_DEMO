import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "../pages/LoginPage";
import { AppProviders } from "./providers";

function renderWorkspace() {
  return render(
    <MemoryRouter>
      <AppProviders>
        <LoginPage />
      </AppProviders>
    </MemoryRouter>,
  );
}

describe("workspace theme", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("opens in dark mode when no preference is saved", () => {
    renderWorkspace();

    expect(screen.getByRole("heading", { name: "Open your workspace" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("switches both ways and saves the choice without resetting the current screen", () => {
    renderWorkspace();

    const heading = screen.getByRole("heading", { name: "Open your workspace" });
    const password = screen.getByLabelText("Demo password");
    fireEvent.click(screen.getByRole("button", { name: /^Manager/ }));
    fireEvent.change(password, { target: { value: "keep-my-input" } });

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("peopleflow.theme")).toBe("light");
    expect(screen.getByRole("heading", { name: "Open your workspace" })).toBe(heading);
    expect(screen.getByLabelText("Demo password")).toBe(password);
    expect(password).toHaveValue("keep-my-input");
    expect(screen.getByRole("button", { name: /^Manager/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("peopleflow.theme")).toBe("dark");
    expect(screen.getByRole("heading", { name: "Open your workspace" })).toBe(heading);
    expect(password).toHaveValue("keep-my-input");
    expect(screen.getByRole("button", { name: /^Manager/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("restores the chosen theme when the application mounts again", () => {
    const workspace = renderWorkspace();
    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    workspace.unmount();
    delete document.documentElement.dataset.theme;

    renderWorkspace();

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Open your workspace" })).toBeVisible();
  });

  it("still opens and switches themes when browser storage is unavailable", () => {
    const originalGetItem = Storage.prototype.getItem;
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (
      this: Storage,
      key: string,
    ) {
      if (this === localStorage) throw new DOMException("Storage is blocked", "SecurityError");
      return originalGetItem.call(this, key);
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      if (this === localStorage) throw new DOMException("Storage is blocked", "SecurityError");
      originalSetItem.call(this, key, value);
    });

    renderWorkspace();

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Open your workspace" })).toBeVisible();
    expect(screen.getByLabelText("Demo password")).toBeEnabled();
  });
});
