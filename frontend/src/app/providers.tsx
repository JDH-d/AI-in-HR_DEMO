import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useMemo, useState } from "react";
import { login as loginRequest, parseStoredUser } from "../api/client";
import type { Role, User } from "../api/types";
import { ThemeProvider } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1 } },
});
type AuthValue = {
  token: string;
  user: User | null;
  login: (role: Role, password: string) => Promise<void>;
  logout: () => void;
};
const AuthContext = createContext<AuthValue | null>(null);

function readStoredSession(): { token: string; user: User | null } {
  const user = parseStoredUser(sessionStorage.getItem("pf_user"));
  const token = sessionStorage.getItem("pf_token") ?? "";
  return user && token ? { token, user } : { token: "", user: null };
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [session, setSession] = useState(readStoredSession);
  const value = useMemo<AuthValue>(
    () => ({
      token: session.token,
      user: session.user,
      login: async (role, password) => {
        const result = await loginRequest(role, password);
        setSession(result);
        sessionStorage.setItem("pf_token", result.token);
        sessionStorage.setItem("pf_user", JSON.stringify(result.user));
      },
      logout: () => {
        setSession({ token: "", user: null });
        sessionStorage.removeItem("pf_token");
        sessionStorage.removeItem("pf_user");
        queryClient.clear();
      },
    }),
    [session],
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Auth provider missing");
  return value;
}
