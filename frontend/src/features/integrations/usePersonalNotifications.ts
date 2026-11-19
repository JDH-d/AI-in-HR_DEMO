import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../app/providers";

export type Provider = "slack" | "discord";
export type PersonalIntegration = {
  provider: Provider;
  configured: boolean;
  enabled: boolean;
  connected: boolean;
  external_user_id: string | null;
  connection_error?: string;
  pending: { challenge_id: string; external_user_id: string } | null;
};
export type PersonalIntegrations = { items: PersonalIntegration[] };
type LinkCode = { code: string; command: string; expires_at: number };
export const providerName = (provider: Provider) => provider === "slack" ? "Slack" : "Discord";

export function usePersonalNotifications() {
  const { token, user } = useAuth();
  const cache = useQueryClient();
  const key = ["personal-integrations", user?.id];
  const query = useQuery({ queryKey: key, queryFn: () => api<PersonalIntegrations>("/api/v1/me/integrations", token), refetchInterval: 5000 });
  const [codes, setCodes] = useState<Partial<Record<Provider, LinkCode>>>({});
  const [disconnect, setDisconnect] = useState<Provider | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const expiry = Object.values(codes).reduce((next, code) => Math.min(next, code.expires_at * 1000), Infinity);
    if (!Number.isFinite(expiry)) return;
    const timer = setTimeout(() => {
      setCodes(current => Object.fromEntries(Object.entries(current).filter(([, code]) => code.expires_at * 1000 > Date.now())));
      setNotice("A connection code expired. Generate a new code to continue.");
    }, Math.max(0, expiry - Date.now()));
    return () => clearTimeout(timer);
  }, [codes]);
  const action = useMutation({
    mutationFn: async ({ provider, kind, challengeId }: { provider: Provider; kind: "code" | "confirm" | "disconnect" | "test"; challengeId?: string }) => {
      const path = `/api/v1/me/integrations/${provider}`;
      if (kind === "code") {
        const code = await api<LinkCode>(`${path}/link-code`, token, { method: "POST" });
        setCodes(current => ({ ...current, [provider]: code }));
      } else if (kind === "test") {
        await api(`${path}/test`, token, { method: "POST" });
        setNotice(`${providerName(provider)} test accepted for delivery to your personal account. No request was changed.`);
      } else {
        const result = await api<PersonalIntegrations>(kind === "confirm" ? `${path}/confirm` : path, token,
          { method: kind === "confirm" ? "POST" : "DELETE", ...(kind === "confirm" ? { body: JSON.stringify({ challenge_id: challengeId }) } : {}) });
        cache.setQueryData(key, result);
        setCodes(current => { const next = { ...current }; delete next[provider]; return next; });
        setDisconnect(null);
        setNotice(`${providerName(provider)} ${kind === "confirm" ? "account connected" : "connection removed"}.`);
      }
      await cache.invalidateQueries({ queryKey: key });
    },
  });
  const run = (variables: Parameters<typeof action.mutate>[0]) => { setNotice(""); action.mutate(variables); };
  return {user, query, codes, disconnect, setDisconnect, notice, action, run};
}
