import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { useRequestForm } from "./useRequestForm";
import type { WorkflowRequest } from "../../api/types";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
beforeEach(() => { vi.mocked(api).mockReset(); });
afterEach(() => vi.unstubAllGlobals());
vi.mock("../../app/providers", () => ({
  useAuth: () => ({ token: "test", user: { manager_id: "manager.demo" } }),
}));

it("retries submission using the already saved draft after a temporary failure", async () => {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const onSubmitted = vi.fn();
  const { result } = renderHook(() => useRequestForm(true, null, onSubmitted), {
    wrapper,
  });
  act(() => {
    result.current.setType("document");
    result.current.setTitle("Employment letter");
    result.current.setComment("Employment letter");
  });
  await waitFor(() => expect(result.current.valid).toBe(true));
  vi.mocked(api)
    .mockResolvedValueOnce({ request: { id: "saved-draft", revision: 1 } })
    .mockRejectedValueOnce(new Error("Temporary failure"))
    .mockResolvedValueOnce({
      request: { id: "saved-draft", status: "in_review" },
    });
  await act(async () => {
    await result.current.mutation.mutateAsync("submit").catch(() => {});
  });
  await waitFor(() => expect(result.current.error).toBe("Temporary failure"));
  await act(async () => {
    await result.current.mutation.mutateAsync("submit");
  });
  expect(vi.mocked(api).mock.calls.map((call) => call[0])).toEqual([
    "/api/v1/requests",
    "/api/v1/requests/saved-draft/submit",
    "/api/v1/requests/saved-draft/submit",
  ]);
  expect(onSubmitted).toHaveBeenCalledOnce();
});

it("keeps local edits when a refreshed draft arrives from another editor", async () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const initial: WorkflowRequest = { id: "r1", number: 1, title: "Original title", comment: "Original description", priority: "normal", revision: 1, review_round: 1, type: "document", type_label: "Document", start_date: null, end_date: null, duration_days: null, applicant: "employee.demo", approver: "manager.demo", status: "draft", created_at: "2030", updated_at: "2030" };
  const { result, rerender } = renderHook(({ draft }) => useRequestForm(true, draft, vi.fn()), { wrapper, initialProps: { draft: initial } });
  act(() => { result.current.setTitle("My unsaved title"); result.current.setComment("My unsaved description"); });
  rerender({ draft: { ...initial, title: "Other editor title", priority: "high", revision: 2 } });
  expect(result.current.title).toBe("My unsaved title");
  expect(result.current.comment).toBe("My unsaved description");
  expect(result.current.conflict).toBe(true);
  await act(async () => { await result.current.mutation.mutateAsync("save").catch(() => {}); });
  expect(api).not.toHaveBeenCalled();
  act(() => result.current.reviewLatest());
  expect(result.current.conflict).toBe(false);
  expect(result.current.priority).toBe("high");
  expect(result.current.title).toBe("My unsaved title");
  expect(result.current.comment).toBe("My unsaved description");
  vi.mocked(api).mockResolvedValueOnce({ request: { ...initial, revision: 3 } });
  await act(async () => { await result.current.mutation.mutateAsync("save"); });
  expect(JSON.parse(String(vi.mocked(api).mock.calls[0][2]?.body))).toMatchObject({ title: "My unsaved title", comment: "My unsaved description", priority: "high", expected_revision: 2 });
});

it("reuses one creation key after a committed draft response is lost and resets it for the next form", async () => {
  // Mobile HTTP LAN previews have getRandomValues but no randomUUID.
  const provider = globalThis.crypto;
  vi.stubGlobal("crypto", { getRandomValues: (buffer: Uint8Array<ArrayBuffer>) => provider.getRandomValues(buffer) });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const saved = vi.fn();
  const persisted = new Map<string, WorkflowRequest>();
  let loseFirstResponse = true;
  vi.mocked(api).mockImplementation(async (_path, _token, options) => {
    const fields = JSON.parse(String(options?.body));
    expect(fields.creation_key).toMatch(/^[0-9a-f-]{36}$/i);
    const key = fields.creation_key as string;
    if (!persisted.has(key)) persisted.set(key, { ...fields, id: `saved-${persisted.size + 1}`, number: persisted.size + 1, status: "draft", revision: 1 } as WorkflowRequest);
    if (loseFirstResponse) { loseFirstResponse = false; throw new Error("The response was lost"); }
    return { request: persisted.get(key) } as never;
  });
  const { result, rerender } = renderHook(({ open }) => useRequestForm(open, null, saved), { wrapper, initialProps: { open: true } });
  act(() => { result.current.setType("document"); result.current.setTitle("Saved once"); result.current.setComment("Relevant saved details"); });
  await act(async () => { await result.current.mutation.mutateAsync("save").catch(() => {}); });
  expect(result.current.error).toBe("The response was lost");
  expect(result.current.title).toBe("Saved once");
  await act(async () => { await result.current.mutation.mutateAsync("save"); });
  expect(persisted.size).toBe(1);
  expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: "saved-1", title: "Saved once" }), "save");
  const firstKey = JSON.parse(String(vi.mocked(api).mock.calls[0][2]?.body)).creation_key;
  expect(JSON.parse(String(vi.mocked(api).mock.calls[1][2]?.body)).creation_key).toBe(firstKey);
  rerender({ open: false });
  rerender({ open: true });
  await act(async () => { await result.current.mutation.mutateAsync("save"); });
  expect(persisted.size).toBe(2);
  expect(JSON.parse(String(vi.mocked(api).mock.calls[2][2]?.body)).creation_key).not.toBe(firstKey);
});

it("preserves edited fields and the same creation key when recovery reports a different saved draft", async () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const saved = vi.fn();
  vi.mocked(api).mockRejectedValueOnce(new Error("The response was lost"))
    .mockRejectedValueOnce(new Error("REQ-000042 was already saved. Open it in My requests to review the saved fields. Your changes were not applied."));
  const { result } = renderHook(() => useRequestForm(true, null, saved), { wrapper });
  act(() => { result.current.setType("document"); result.current.setTitle("Original title"); result.current.setComment("Original explanation"); });
  await act(async () => { await result.current.mutation.mutateAsync("save").catch(() => {}); });
  act(() => { result.current.setTitle("My revised title"); result.current.setPriority("urgent"); });
  await act(async () => { await result.current.mutation.mutateAsync("save").catch(() => {}); });
  const bodies = vi.mocked(api).mock.calls.map(call => JSON.parse(String(call[2]?.body)));
  expect(bodies[1].creation_key).toBe(bodies[0].creation_key);
  expect(bodies[1].creation_key).toBeTruthy();
  expect(result.current.error).toContain("REQ-000042");
  expect(result.current.title).toBe("My revised title");
  expect(result.current.priority).toBe("urgent");
  expect(result.current.dirty).toBe(true);
  expect(saved).not.toHaveBeenCalled();
});
