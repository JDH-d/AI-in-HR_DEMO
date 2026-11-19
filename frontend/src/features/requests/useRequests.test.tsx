import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { useRequests } from "./useRequests";

vi.mock("../../api/client", () => ({ api: vi.fn() }));
const identity = vi.hoisted(() => ({ role: "manager", id: "manager.demo" }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "synthetic", user: identity }) }));

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); focusManager.setFocused(true);
  identity.role = "manager"; identity.id = "manager.demo";
});
afterEach(() => { cleanup(); focusManager.setFocused(undefined); vi.useRealTimers(); });

function mount() {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, refetchOnWindowFocus: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>;
  return renderHook(() => {
    const query = useRequests(identity.role === "manager" ? "manager-requests" : "requests", { status: "submitted", priority: "high" });
    return { data: query.data, isSuccess: query.isSuccess };
  }, { wrapper });
}

it("refreshes the Manager queue every minute so changed statuses and attention match its overview", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({ requests: [{ id: "request-one", status: "submitted", manager_attention: { overdue: false } }], total: 1, counts: { submitted: 1 } } as never)
    .mockResolvedValue({ requests: [], total: 0, counts: { submitted: 0, in_review: 1 } } as never);
  const { result } = mount();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(result.current.data?.requests[0].id).toBe("request-one");
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(59_998); });
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(2); });
  expect(vi.mocked(api)).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api)).toHaveBeenLastCalledWith("/api/v1/requests?status=submitted&priority=high", "synthetic");
  expect(result.current.data?.requests).toEqual([]);
  expect(result.current.data?.counts.in_review).toBe(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(vi.mocked(api)).toHaveBeenCalledTimes(3);
});

it("does not add periodic polling to the Employee request list", async () => {
  identity.role = "employee"; identity.id = "employee.demo";
  vi.mocked(api).mockResolvedValue({ requests: [], total: 0, counts: {} } as never);
  const { result } = mount();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(result.current.isSuccess).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(180_000); });
  expect(vi.mocked(api)).toHaveBeenCalledOnce();
});
