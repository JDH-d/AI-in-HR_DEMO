import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ConversationList, RequestList } from "../../api/types";
import { useAuth } from "../../app/providers";

/** Read the same owner-scoped data as My requests and My chats. */
export function useEmployeeHome() {
  const { token, user } = useAuth();
  const enabled = user?.role === "employee" && Boolean(token);
  const requests = (view: string, limit: number) => ({
    queryKey: ["requests", "home", user?.id, view],
    queryFn: ({ signal }: { signal: AbortSignal }) => api<RequestList>(
      `/api/v1/requests?${new URLSearchParams({ ...(view ? { status: view } : {}), limit: String(limit), sort: "updated_at", order: "desc" })}`, token, { signal },
    ),
    enabled,
    refetchInterval: 30_000,
  });
  const recent = useQuery(requests("", 5));
  const replies = useQuery(requests("needs_information", 3));
  const drafts = useQuery(requests("draft", 3));
  const chats = useQuery({
    queryKey: ["conversations", user?.id, { view: "home-preview" }],
    queryFn: ({ signal }) => api<ConversationList>("/api/v1/conversations?limit=3&offset=0", token, { signal }),
    enabled,
  });
  return { recent, replies, drafts, chats };
}
