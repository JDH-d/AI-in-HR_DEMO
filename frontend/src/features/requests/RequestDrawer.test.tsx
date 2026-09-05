import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
  afterEach(cleanup);

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

  it("keeps the success state when its parent receives the new request ID", async () => {
    apiMock
      .mockResolvedValueOnce({ request: draft })
      .mockResolvedValueOnce({ request: { ...draft, status: "in_review" } });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    function RequestHost() {
      const [request, setRequest] = useState<WorkflowRequest | null>(null);
      const [open, setOpen] = useState(true);
      return (
        <RequestDrawer
          open={open}
          initial={request}
          onOpenChange={setOpen}
          onSubmitted={setRequest}
        />
      );
    }
    render(
      <QueryClientProvider client={queryClient}>
        <RequestHost />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("First day"), {
      target: { value: "2030-04-10" },
    });
    fireEvent.change(screen.getByLabelText(/Planning note/), {
      target: { value: "Handoff is ready." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send for approval" }));

    expect(await screen.findByText("We sent your request to your manager.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send for approval" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument(), {
      timeout: 3500,
    });
    expect(apiMock).toHaveBeenCalledTimes(2);
  });

  it("labels closing honestly and explains discarded edits only after a change", () => {
    const onOpenChange = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RequestDrawer open initial={draft} onOpenChange={onOpenChange} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("Closing will discard unsent changes.")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Planning note/), {
      target: { value: "Updated handoff." },
    });
    expect(screen.getByText("Closing will discard unsent changes.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Keep as draft" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiMock).not.toHaveBeenCalled();
  });

  it("reports sick leave without requiring a planning note", async () => {
    const sickLeave = { ...draft, type: "sick_leave", comment: "" } as const;
    apiMock
      .mockResolvedValueOnce({ request: sickLeave })
      .mockResolvedValueOnce({ request: { ...sickLeave, status: "reported" } });
    const onOpenChange = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RequestDrawer open onOpenChange={onOpenChange} />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("Request type"), {
      target: { value: "sick_leave" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Report sick leave" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    const payload = JSON.parse(apiMock.mock.calls[0][2].body);
    expect(payload.type).toBe("sick_leave");
    expect(payload.comment).toBe("");
    expect(payload.details.time_away).toBe("full_day");
  });
});
