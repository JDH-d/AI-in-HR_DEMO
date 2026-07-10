import { z } from "zod";
import type { Role, User } from "./types";

const API = import.meta.env.VITE_API_URL ?? "";
const loginSchema = z.object({
  access_token: z.string(),
  user: z.object({
    id: z.string(), username: z.string(), display_name: z.string(),
    role: z.enum(["employee", "manager", "knowledge_admin"]),
    manager_id: z.string().nullable().optional(),
  }),
});

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = Array.isArray(payload.detail) ? payload.detail.join(" ") : payload.detail;
    throw new ApiError(response.status, detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function login(username: Role, password: string): Promise<{ token: string; user: User }> {
  const raw = await api<unknown>("/api/v1/auth/login", undefined, {
    method: "POST", body: JSON.stringify({ username, password }),
  });
  const parsed = loginSchema.parse(raw);
  return { token: parsed.access_token, user: parsed.user };
}

export async function downloadFile(path: string, token: string, filename: string): Promise<void> {
  const response = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, payload.detail || "Unable to download the document");
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function streamChat(
  token: string,
  messages: { role: string; content: string }[],
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  const response = await fetch(`${API}/api/v1/chat/stream`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  if (!response.ok || !response.body) throw new ApiError(response.status, "Unable to stream response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
}
