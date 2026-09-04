import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowRequest } from "../../api/types";
import { RequestDrawer } from "./RequestDrawer";

const apiMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/client", () => ({ api: apiMock }));
vi.mock("../../app/providers", () => ({
  useAuth: () => ({ token: "demo-token" }),
}));

const draft: WorkflowRequest = {
  id: "pto-draft-1",
  type: "pto",
  type_label: "PTO",
  start_date: "2030-04-10",
  end_date: "2030-04-12",
  duration_days: 3,
  comment: "Handoff is ready.",
  applicant: "employee.demo",
  approver: "manager.demo",
  details: {},
  status: "draft",
  created_at: "2030-04-01T09:00:00Z",
  updated_at: "2030-04-01T09:00:00Z",
};

describe("RequestDrawer", () => {
  beforeEach(() => apiMock.mockReset());

  it("reuses a newly created draft when the first submit attempt fails", async () => {
    apiMock
      .mockResolvedValueOnce({ request: draft })
      .mockRejectedValueOnce(new Error("Submit failed"))
      .mockResolvedValueOnce({ request: { ...draft, status: "in_review" } });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <RequestDrawer open onOpenChange={() => undefined} />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("First day"), {
      target: { value: "2030-04-10" },
    });
    fireEvent.change(screen.getByLabelText("Last day"), {
      target: { value: "2030-04-12" },
    });
    fireEvent.change(screen.getByLabelText(/Planning note/), {
      target: { value: "Handoff is ready." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));

    expect(await screen.findByText("Submit failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));

    expect(await screen.findByText("We sent your request to your manager.")).toBeInTheDocument();
    await waitFor(() => expect(apiMock).toHaveBeenCalledTimes(3));
    expect(apiMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/requests",
      "/api/v1/requests/pto-draft-1/submit",
      "/api/v1/requests/pto-draft-1/submit",
    ]);
  });
});
