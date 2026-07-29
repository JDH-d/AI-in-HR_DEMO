import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { RequestDetail, WorkflowRequest } from "../../api/types";
import { ManagerPage } from "./ManagerPage";

vi.mock("../../api/client", () => ({
  api: vi.fn(),
}));
vi.mock("../../app/providers", () => ({
  useAuth: () => ({
    token: "manager-token",
    user: {
      id: "manager.demo",
      username: "manager",
      display_name: "Demo Manager",
      role: "manager",
    },
    logout: vi.fn(),
  }),
}));

const request: WorkflowRequest = {
  id: "request-1",
  type: "pto",
  type_label: "PTO",
  start_date: "2030-04-10",
  end_date: "2030-04-12",
  duration_days: 3,
  comment: "Family vacation",
  applicant: "employee.demo",
  approver: "manager.demo",
  status: "in_review",
  created_at: "2030-04-01T09:00:00Z",
  updated_at: "2030-04-01T09:01:00Z",
};

describe("Manager request deep links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockImplementation(async path => {
      if (path === "/api/v1/requests") return { requests: [request] };
      if (path === "/api/v1/requests/request-1") {
        return {
          request,
          events: [],
          comments: [],
        } satisfies RequestDetail;
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
  });

  it("opens the exact request from the request query parameter", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <MemoryRouter initialEntries={["/manager?request=request-1"]}>
        <QueryClientProvider client={queryClient}>
          <ManagerPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(api).toHaveBeenCalledWith(
        "/api/v1/requests/request-1",
        "manager-token",
      );
    });
    expect(await screen.findByText("#request-")).toBeInTheDocument();
    expect(screen.getAllByText("Family vacation").length).toBeGreaterThan(0);
  });
});
