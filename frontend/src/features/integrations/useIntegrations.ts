import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAuth } from "../../app/providers";

type Delivery = { id: string; status: string; attempts: number; error: string; updated_at: number; next_attempt_at: number };
export type Integration = {
  provider: "slack" | "discord";
  enabled: boolean; configured: boolean; revision: number; pending: number; configuration_error: string;
  last_delivery: Delivery | null;
  active_delivery: Delivery | null;
  recipients: { employee: boolean; manager: boolean };
};
export type Integrations = { items: Integration[]; app_url: string };

export function useIntegrations() {
  const { token, user } = useAuth();
  const cache = useQueryClient();
  const query = useQuery({ queryKey: ["integrations"], enabled: user?.role === "knowledge_admin", queryFn: () => api<Integrations>("/api/v1/admin/integrations", token), refetchInterval: 3000 });
  const refresh = () => cache.invalidateQueries({ queryKey: ["integrations"] });
  const toggle = useMutation({
    mutationFn: (item: Integration) => api<Integrations>(`/api/v1/admin/integrations/${item.provider}`, token, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled, expected_revision: item.revision }) }),
    onSuccess: data => cache.setQueryData(["integrations"], data),
    onError: () => { void refresh(); },
  });
  const test = useMutation({
    mutationFn: ({provider, audience}: {provider: Integration["provider"]; audience: "employee" | "manager"}) => api<{ id: string; status: string }>(`/api/v1/admin/integrations/${provider}/test`, token, { method: "POST", body: JSON.stringify({audience}) }),
    onSuccess: refresh,
  });
  return { query, toggle, test };
}
