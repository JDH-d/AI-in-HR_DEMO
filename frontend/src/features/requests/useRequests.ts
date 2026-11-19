import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { RequestDetail, RequestList, RequestOptions } from "../../api/types";
import { useAuth } from "../../app/providers";
export function useRequests(key: "requests" | "manager-requests" = "requests", filters: Record<string, string> = {}) {
  const { token, user } = useAuth();
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== ""));
  return useQuery({ queryKey: [key, filters], queryFn: () => api<RequestList>(`/api/v1/requests?${query}`, token), enabled: user?.role !== "knowledge_admin", refetchInterval: user?.role === "manager" ? 60_000 : false });
}

export function useRequestOptions() {
  const { token } = useAuth();
  return useQuery({ queryKey: ["request-options"], queryFn: () => api<RequestOptions>("/api/v1/request-options", token) });
}

export function useRequestDetail(id: string | null) {
  const { token } = useAuth();
  return useQuery({ queryKey: ["request-detail", id], queryFn: () => api<RequestDetail>(`/api/v1/requests/${id}`, token), enabled: Boolean(id), refetchOnWindowFocus: false });
}

export function useRequestRefresh() {
  const client = useQueryClient();
  return () => refreshRequests(client);
}

export function refreshRequests(client: QueryClient, id?: string | null) {
  return Promise.all([
    client.invalidateQueries({ queryKey: ["requests"] }),
    client.invalidateQueries({ queryKey: ["manager-requests"] }),
    client.invalidateQueries({ queryKey: ["manager-overview"] }),
    client.invalidateQueries({ queryKey: ["manager-activity"] }),
    client.invalidateQueries({ queryKey: id ? ["request-detail", id] : ["request-detail"] }),
  ]);
}
