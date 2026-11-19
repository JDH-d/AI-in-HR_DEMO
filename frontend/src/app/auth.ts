import { createContext, useContext } from "react";
import type { User } from "../api/types";

type AuthValue = {
  token: string;
  user: User | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

// Keep context identity independent of UI modules refreshed by Vite.
export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Auth provider missing");
  return value;
}

export type { AuthValue };
