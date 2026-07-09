import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { statusTone } from "../components/ui";
import { App } from "./App";
import { AppProviders } from "./providers";

describe("PeopleFlow application shell", () => {
  beforeEach(() => sessionStorage.clear());

  it("shows all three predefined role workspaces", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AppProviders><App /></AppProviders>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Work questions become")).toBeInTheDocument();
    expect(screen.getByText("Employee")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
    expect(screen.getByText("Knowledge Admin")).toBeInTheDocument();
  });

  it("maps workflow states to consistent semantic tones", () => {
    expect(statusTone("approved")).toBe("success");
    expect(statusTone("submitted")).toBe("warning");
    expect(statusTone("declined")).toBe("danger");
  });
});
