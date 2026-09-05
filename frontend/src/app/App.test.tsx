import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RequestDetail, WorkflowRequest } from "../api/types";
import { statusTone } from "../components/ui";
import { decisionComment, RequestOverview } from "../features/requests/RequestDetails";
import { expectedReturnLabel, requestPeriodLabel } from "../features/requests/requestPresentation";
import { App } from "./App";
import { AppProviders } from "./providers";

describe("PeopleFlow application shell", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });
  afterEach(cleanup);

  it("shows all three predefined role workspaces", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AppProviders>
          <App />
        </AppProviders>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Open your workspace" })).toBeInTheDocument();
    expect(screen.getByText("Employee")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
    expect(screen.getByText("Knowledge Admin")).toBeInTheDocument();
  });

  it("lets users choose a demo account and reveal their password without changing it", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AppProviders>
          <App />
        </AppProviders>
      </MemoryRouter>,
    );

    const employee = screen.getByRole("button", { name: /^Employee/ });
    const manager = screen.getByRole("button", { name: /^Manager/ });
    expect(employee).toHaveAttribute("aria-pressed", "true");
    expect(manager).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(manager);
    expect(manager).toHaveAttribute("aria-pressed", "true");
    expect(employee).toHaveAttribute("aria-pressed", "false");

    const password = screen.getByLabelText("Demo password");
    fireEvent.change(password, { target: { value: "my-demo-password" } });
    expect(password).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("my-demo-password");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveValue("my-demo-password");
    expect(manager).toHaveAttribute("aria-pressed", "true");
  });

  it("maps workflow states to consistent semantic tones", () => {
    expect(statusTone("approved")).toBe("success");
    expect(statusTone("acknowledged")).toBe("success");
    expect(statusTone("in_review")).toBe("warning");
    expect(statusTone("reported")).toBe("warning");
    expect(statusTone("declined")).toBe("danger");
  });

  it("presents sick leave as an availability report", () => {
    const request = {
      id: "sick-1",
      type: "sick_leave",
      type_label: "Sick leave",
      start_date: "2030-04-01",
      end_date: "2030-04-01",
      duration_days: 1,
      comment: "",
      applicant: "employee.demo",
      approver: "manager.demo",
      details: {
        expected_return_date: "2030-04-02",
        expected_return_unknown: false,
        time_away: "full_day",
      },
      status: "reported",
      created_at: "2030-04-01T09:00:00Z",
      updated_at: "2030-04-01T09:00:00Z",
    } as const;

    expect(expectedReturnLabel(request)).not.toBe("Not sure yet");
    expect(requestPeriodLabel(request)).toContain("back");

    render(<RequestOverview request={request} />);
    expect(screen.getByText("Availability report")).toBeInTheDocument();
    expect(screen.queryByText(/medical details/i)).not.toBeInTheDocument();
  });

  it("presents PTO as a planned approval request", () => {
    const request: WorkflowRequest = {
      id: "pto-1",
      type: "pto",
      type_label: "Vacation / PTO",
      start_date: "2030-04-10",
      end_date: "2030-04-12",
      duration_days: 3,
      comment: "I’ll hand over current work before I go.",
      applicant: "employee.demo",
      approver: "manager.demo",
      details: {},
      status: "in_review",
      created_at: "2030-04-01T09:00:00Z",
      updated_at: "2030-04-01T09:00:00Z",
    };

    render(<RequestOverview request={request} />);

    expect(screen.getByText("Approval request")).toBeInTheDocument();
    expect(screen.getByText("3 calendar days")).toBeInTheDocument();
    expect(screen.getByText("Planning note")).toBeInTheDocument();
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
        details: {},
        status: "declined",
        created_at: "2030-01-01T09:00:00Z",
        updated_at: "2030-01-01T10:00:00Z",
      },
      comments: [],
      events: [
        {
          id: "event-1",
          event_type: "status_changed",
          from_status: "in_review",
          to_status: "declined",
          actor: "manager.demo",
          details: { comment: "Coverage is unavailable." },
          created_at: "2030-01-01T10:00:00Z",
        },
      ],
    } satisfies RequestDetail;

    expect(decisionComment(detail)).toBe("Coverage is unavailable.");
  });
});
