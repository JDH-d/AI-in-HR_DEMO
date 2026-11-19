import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { statusTone } from "../components/ui";
import type { RequestDetail } from "../api/types";
import { decisionComment, latestDecisionEvent } from "../features/requests/RequestDetails";
import { App } from "./App";
import { AppProviders } from "./providers";

describe("PeopleFlow application shell", () => {
  beforeEach(() => sessionStorage.clear());

  it("shows all three predefined role workspaces", async () => {
    document.title = "My requests · PeopleFlow AI";
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AppProviders><App /></AppProviders>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", {name: "Sign in to your workspace"})).toBeInTheDocument();
    expect(document.title).toBe("Sign in · PeopleFlow AI");
    expect(screen.getByText("Employee")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
    expect(screen.getByText("Knowledge Admin")).toBeInTheDocument();
  });

  it("maps workflow states to consistent semantic tones", () => {
    expect(statusTone("approved")).toBe("success");
    expect(statusTone("in_review")).toBe("warning");
    expect(statusTone("rejected")).toBe("danger");
  });

  it("exposes the manager decision note from the request timeline", () => {
    const detail = {
      request: {
        id: "request-1", number: 1, title: "Vacation", priority: "normal", revision: 4, review_round: 1,
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
      comments: [], attachments: [], allowed_actions: ["appeal"], procedure: "Same criteria", policy_version: "v1",
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
    detail.events.push({ ...detail.events[0], id: "comment-event", event_type: "comment_added", actor: "employee.demo", details: { comment: "Please reconsider." } });
    detail.events.push({ ...detail.events[0], id: "migration-event", event_type: "schema_migrated", actor: "system", details: { comment: "Imported" } });
    expect(decisionComment(detail)).toBe("Coverage is unavailable.");
    expect(latestDecisionEvent(detail)?.actor).toBe("manager.demo");
  });
});
