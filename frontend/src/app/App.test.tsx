import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { statusTone } from "../components/ui";
import type { RequestDetail } from "../api/types";
import { decisionComment } from "../features/requests/RequestDetails";
import { App } from "./App";
import { AppProviders } from "./providers";
import { destinationForRole } from "../pages/LoginPage";

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
    expect(statusTone("in_review")).toBe("warning");
    expect(statusTone("declined")).toBe("danger");
  });

  it("exposes the manager decision note from the request timeline", () => {
    const detail = {
      request: {
        id: "request-1",
        type: "pto",
        type_label: "PTO",
        start_date: "2030-01-01",
        end_date: "2030-01-02",
        duration_days: 2,
        comment: "Vacation",
        applicant: "employee.demo",
        approver: "manager.demo",
        status: "declined",
        created_at: "2030-01-01T09:00:00Z",
        updated_at: "2030-01-01T10:00:00Z",
      },
      comments: [],
      events: [{
        id: "event-1",
        event_type: "status_changed",
        from_status: "in_review",
        to_status: "declined",
        actor: "manager.demo",
        details: { comment: "Coverage is unavailable." },
        created_at: "2030-01-01T10:00:00Z",
      }],
    } satisfies RequestDetail;

    expect(decisionComment(detail)).toBe("Coverage is unavailable.");
  });

  it("preserves safe manager request links after login", () => {
    expect(destinationForRole("manager", "/manager?request=request-1")).toBe(
      "/manager?request=request-1",
    );
    expect(destinationForRole("employee", "/manager?request=request-1")).toBe(
      "/employee",
    );
    expect(destinationForRole("manager", "https://example.com")).toBe("/manager");
  });
});
