import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { login as loginRequest } from "../api/client";
import type { User } from "../api/types";
import { AuthContext, type AuthValue } from "./auth";
import { UnsavedChangesProvider } from "../components/UnsavedChanges";
import { ThemeSync } from "../components/ThemeControl";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, retry: 1 } },
});
export { useAuth } from "./auth";

export function AppProviders({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("pf_token") ?? "",
  );
  const [user, setUser] = useState<User | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("pf_user") ?? "null");
    } catch {
      return null;
    }
  });
  const value = useMemo<AuthValue>(
    () => ({
      token,
      user,
      login: async (username, password) => {
        const result = await loginRequest(username, password);
        queryClient.clear();
        setToken(result.token);
        setUser(result.user);
        sessionStorage.setItem("pf_token", result.token);
        sessionStorage.setItem("pf_user", JSON.stringify(result.user));
      },
      logout: () => {
        setToken("");
        setUser(null);
        sessionStorage.removeItem("pf_token");
        sessionStorage.removeItem("pf_user");
        queryClient.clear();
      },
    }),
    [token, user],
  );
  useEffect(() => {
    const expire = (event: Event) => {
      if ((event as CustomEvent).detail === token) value.logout();
    };
    window.addEventListener("auth-expired", expire);
    return () => window.removeEventListener("auth-expired", expire);
  }, [token, value]);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={value}><ThemeSync/><UnsavedChangesProvider>{children}</UnsavedChangesProvider></AuthContext.Provider>
    </QueryClientProvider>
  );
}

