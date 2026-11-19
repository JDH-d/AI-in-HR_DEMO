import { z } from "zod";
import type { User } from "./types";

const API = import.meta.env.VITE_API_URL ?? "";
const loginSchema = z.object({
  access_token: z.string(),
  user: z.object({
    id: z.string(),
    username: z.string(),
    display_name: z.string(),
    role: z.enum(["employee", "manager", "knowledge_admin"]),
    manager_id: z.string().nullable().optional(),
  }),
});

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function checkedFetch(
  path: string,
  token?: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401 && token)
      window.dispatchEvent(new CustomEvent("auth-expired", { detail: token }));
    const payload = await response.json().catch(() => ({}));
    const detail = Array.isArray(payload.detail)
      ? payload.detail
          .map((item: string | { msg?: string }) =>
            typeof item === "string" ? item : (item.msg ?? "Invalid value"),
          )
          .join(" ")
      : payload.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string"
        ? detail
        : `Request failed (${response.status})`,
    );
  }
  return response;
}

export async function api<T>(
  path: string,
  token?: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await checkedFetch(path, token, init);
  return response.json() as Promise<T>;
}

export async function login(
  username: string,
  password: string,
): Promise<{ token: string; user: User }> {
  const raw = await api<unknown>("/api/v1/auth/login", undefined, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const parsed = loginSchema.parse(raw);
  return { token: parsed.access_token, user: parsed.user };
}

export async function downloadFile(
  path: string,
  token: string,
  filename: string,
): Promise<void> {
  const response = await checkedFetch(path, token);
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
  message: { conversationId: string; content: string; requestId: string },
  onEvent: (event: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await checkedFetch(`/api/v1/conversations/${message.conversationId}/messages/stream`, token, {
    method: "POST",
    body: JSON.stringify({ content: message.content, request_id: message.requestId }),
    signal,
  });
  if (!response.body)
    throw new ApiError(response.status, "Unable to stream response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = false;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "complete") complete = true;
    onEvent(event);
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      lines.forEach(consume);
    }
    consume(buffer + decoder.decode());
    if (!complete)
      throw new Error("The response was interrupted. Please try again.");
  } finally {
    reader.releaseLock();
  }
}
