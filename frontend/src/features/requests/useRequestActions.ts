import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, downloadFile } from "../../api/client";
import { useAuth } from "../../app/providers";
import { refreshRequests, useRequestDetail } from "./useRequests";

export function useRequestActions(id: string | null) {
  const { token } = useAuth();
  const cache = useQueryClient();
  const detail = useRequestDetail(id);
  const mutation = useMutation({
    mutationFn: ({ path, body }: { path: string; body: Record<string, unknown> | FormData }) => {
      if (!detail.data || detail.isError || detail.isFetching) throw new Error("Reload the request before making changes.");
      const revision = detail.data.request.revision;
      if (body instanceof FormData) body.set("expected_revision", String(revision));
      return api(`/api/v1/requests/${id}/${path}`, token, {
        method: "POST", body: body instanceof FormData ? body : JSON.stringify({ ...body, expected_revision: revision }),
      });
    },
    onSuccess: () => refreshRequests(cache, id),
    onError: () => { void refreshRequests(cache, id); },
  });
  const download = (attachmentId: string, filename: string) => downloadFile(`/api/v1/requests/${id}/attachments/${attachmentId}`, token, filename);
  return { detail, mutation, download };
}
