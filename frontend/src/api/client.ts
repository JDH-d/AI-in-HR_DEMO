import { z } from "zod";
import type { ChatStreamEvent, Role, User } from "./types";

const API = import.meta.env.VITE_API_URL ?? "";
const userSchema = z.object({
  id: z.string(),
  username: z.string(),
  display_name: z.string(),
  role: z.enum(["employee", "manager", "knowledge_admin"]),
  manager_id: z.string().nullable().optional(),
});
const loginSchema = z.object({ access_token: z.string(), user: userSchema });
const sourceSchema = z.object({
  source: z.string(),
  title: z.string(),
  section: z.string(),
  category: z.string(),
  version: z.string(),
  excerpt: z.string(),
  score: z.number(),
});
const workflowRequestSchema = z.object({
  id: z.string(),
  type: z.enum(["pto", "sick_leave"]),
  type_label: z.string(),
  start_date: z.string().nullable(),
  end_date: z.string().nullable(),
  duration_days: z.number().nullable(),
  comment: z.string(),
  applicant: z.string(),
  approver: z.string(),
  status: z.enum([
    "draft",
    "in_review",
    "reported",
    "acknowledged",
    "approved",
    "declined",
    "cancelled",
  ]),
  details: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  updated_at: z.string(),
  validation_errors: z.array(z.string()).optional(),
});
const chatStreamEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("start") }),
  z.object({ type: z.enum(["token", "replace"]), content: z.string() }),
  z.object({ type: z.literal("error"), message: z.string() }),
  z.object({
    type: z.literal("complete"),
    intent: z.string(),
    language: z.string(),
    outcome_code: z.string(),
    sources: z.array(sourceSchema),
    workflow_request: workflowRequestSchema.nullable(),
    conversation_id: z.string(),
  }),
]);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorDetail(payload: unknown): string | undefined {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) return undefined;
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return undefined;
  const messages = detail.flatMap((item) => {
    if (typeof item === "string") return [item];
    if (
      typeof item === "object" &&
      item !== null &&
      "msg" in item &&
      typeof item.msg === "string"
    ) {
      return [item.msg];
    }
    return [];
  });
  return messages.length ? messages.join(" ") : undefined;
}

export async function api<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => ({}));
    const detail = errorDetail(payload);
    throw new ApiError(response.status, detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function login(
  username: Role,
  password: string,
): Promise<{ token: string; user: User }> {
  const raw = await api<unknown>("/api/v1/auth/login", undefined, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const parsed = loginSchema.parse(raw);
  return { token: parsed.access_token, user: parsed.user };
}

export function parseStoredUser(value: string | null): User | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    const result = userSchema.safeParse(parsed);
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

export async function downloadFile(path: string, token: string, filename: string): Promise<void> {
  const response = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => ({}));
    const detail =
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
        ? payload.detail
        : "Unable to download the document";
    throw new ApiError(response.status, detail);
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
  message: string,
  onEvent: (event: ChatStreamEvent) => void,
  conversationId?: string,
): Promise<void> {
  const response = await fetch(`${API}/api/v1/chat/stream`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: [{ role: "user", content: message }],
      conversation_id: conversationId,
    }),
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      errorDetail(payload) || `Unable to stream response (${response.status})`,
    );
  }
  if (!response.body) throw new ApiError(response.status, "Unable to stream response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminalEvent = false;
  const emit = (line: string) => {
    if (!line.trim()) return;
    const event = chatStreamEventSchema.parse(JSON.parse(line));
    if (event.type === "complete" || event.type === "error") sawTerminalEvent = true;
    onEvent(event);
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) emit(line);
  }
  buffer += decoder.decode();
  emit(buffer);
  if (!sawTerminalEvent) {
    throw new ApiError(502, "The assistant response ended before it was complete.");
  }
}
