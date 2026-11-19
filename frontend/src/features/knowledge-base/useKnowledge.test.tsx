import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { AISettingsResponse } from "../../api/types";
import { useAISettings } from "./useKnowledge";

vi.mock("../../api/client", () => ({ api: vi.fn(), downloadFile: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test" }) }));

it("previews unsaved settings without applying them and applies only on save", async () => {
  const saved: AISettingsResponse = { settings: { strict_grounding: true, concise_answers: true, ask_clarifying_questions: true, suggest_next_steps: true, show_sources: true, auto_index_uploads: true }, system_prompt: "Saved prompt", default_system_prompt: "Default prompt" };
  vi.mocked(api).mockImplementation(async (_path, _token, options) => {
    if (options?.method === "POST") return { answer: "Preview", sources: [], intent: "work", latency_ms: 1 } as never;
    if (options?.method === "PUT") return { ...saved, ...JSON.parse(String(options.body)) } as never;
    return saved as never;
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(() => useAISettings(), { wrapper });
  await waitFor(() => expect(result.current.prompt).toBe("Saved prompt"));
  act(() => result.current.changePrompt("Unsaved prompt"));
  await act(async () => { await result.current.preview.mutateAsync(); });
  expect(result.current.dirty).toBe(true);
  expect(client.getQueryData<AISettingsResponse>(["ai-settings"])?.system_prompt).toBe("Saved prompt");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "PUT")).toBe(false);
  expect(JSON.parse(String(vi.mocked(api).mock.calls.find(call => call[2]?.method === "POST")?.[2]?.body)).system_prompt).toBe("Unsaved prompt");
  await act(async () => { await result.current.save.mutateAsync(); });
  await waitFor(() => expect(result.current.dirty).toBe(false));
  expect(client.getQueryData<AISettingsResponse>(["ai-settings"])?.system_prompt).toBe("Unsaved prompt");
});

it("preserves local edits when saved settings refresh in the background", async () => {
  const saved: AISettingsResponse = { settings: { strict_grounding: true, concise_answers: true, ask_clarifying_questions: true, suggest_next_steps: true, show_sources: true, auto_index_uploads: true }, system_prompt: "Saved prompt", default_system_prompt: "Default prompt" };
  vi.mocked(api).mockResolvedValue(saved);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(() => useAISettings(), { wrapper });
  await waitFor(() => expect(result.current.prompt).toBe("Saved prompt"));
  act(() => result.current.changePrompt("Draft that must survive"));
  act(() => client.setQueryData(["ai-settings"], {...saved, system_prompt: "Refreshed server instruction"}));
  await waitFor(() => expect(result.current.loaded.data?.system_prompt).toBe("Refreshed server instruction"));
  expect(result.current.prompt).toBe("Draft that must survive");
  expect(result.current.dirty).toBe(true);
  act(() => result.current.reset());
  expect(result.current.prompt).toBe("Refreshed server instruction");
  expect(result.current.dirty).toBe(false);
});
