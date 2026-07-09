import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { login as loginRequest } from "../api/client";
import type { Role, User } from "../api/types";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1 } } });
type AuthValue = { token: string; user: User | null; login: (role: Role, password: string) => Promise<void>; logout: () => void };
const AuthContext = createContext<AuthValue | null>(null);

export function AppProviders({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => sessionStorage.getItem("pf_token") ?? "");
  const [user, setUser] = useState<User | null>(() => {
    try { return JSON.parse(sessionStorage.getItem("pf_user") ?? "null"); } catch { return null; }
  });
  const value = useMemo<AuthValue>(() => ({
    token, user,
    login: async (role, password) => {
      const result = await loginRequest(role, password);
      setToken(result.token); setUser(result.user);
      sessionStorage.setItem("pf_token", result.token);
      sessionStorage.setItem("pf_user", JSON.stringify(result.user));
    },
    logout: () => { setToken(""); setUser(null); sessionStorage.clear(); queryClient.clear(); },
  }), [token, user]);
  return <QueryClientProvider client={queryClient}><AuthContext.Provider value={value}>{children}</AuthContext.Provider></QueryClientProvider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Auth provider missing");
  return value;
}
