import {
  ArrowCounterClockwise,
  ArrowsClockwise,
  FloppyDisk,
  Play,
  SlidersHorizontal,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AISettings, AISettingsResponse, AISettingsTestResult } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Card, fieldClass } from "../../components/ui";

const defaultSettings: AISettings = {
  strict_grounding: true,
  concise_answers: true,
  ask_clarifying_questions: true,
  suggest_next_steps: true,
  show_sources: true,
  auto_index_uploads: true,
};

const controls: { key: keyof AISettings; label: string; copy: string }[] = [
  {
    key: "strict_grounding",
    label: "Strict grounding",
    copy: "Answer only when company sources provide reliable evidence.",
  },
  {
    key: "concise_answers",
    label: "Concise answers",
    copy: "Prefer short, scannable responses over long explanations.",
  },
  {
    key: "ask_clarifying_questions",
    label: "Ask clarifying questions",
    copy: "Request missing context instead of guessing employee intent.",
  },
  {
    key: "suggest_next_steps",
    label: "Suggest next steps",
    copy: "End useful answers with one practical action when appropriate.",
  },
  {
    key: "show_sources",
    label: "Show sources",
    copy: "Expose supporting document evidence in the employee chat.",
  },
  {
    key: "auto_index_uploads",
    label: "Auto-index uploads",
    copy: "Make new documents searchable immediately after upload.",
  },
];

export function AISettingsPanel() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [settings, setSettings] = useState<AISettings>(defaultSettings);
  const [prompt, setPrompt] = useState("");
  const [question, setQuestion] = useState("When are salaries paid?");
  const loaded = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (loaded.data) {
      setSettings(loaded.data.settings);
      setPrompt(loaded.data.system_prompt);
    }
  }, [loaded.data]);

  const dirty = loaded.data
    ? JSON.stringify(settings) !== JSON.stringify(loaded.data.settings) ||
      prompt !== loaded.data.system_prompt
    : false;

  const save = useMutation({
    mutationFn: () =>
      api<AISettingsResponse>("/api/v1/admin/ai-settings", token, {
        method: "PUT",
        body: JSON.stringify({ settings, system_prompt: prompt }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-settings"], data);
    },
  });

  const preview = useMutation({
    mutationFn: () =>
      api<AISettingsTestResult>("/api/v1/admin/ai-settings/test", token, {
        method: "POST",
        body: JSON.stringify({ question, settings, system_prompt: prompt }),
      }),
  });

  const changeSetting = (key: keyof AISettings, checked: boolean) => {
    setSettings((current) => ({ ...current, [key]: checked }));
    preview.reset();
    save.reset();
  };
  const changePrompt = (value: string) => {
    setPrompt(value);
    preview.reset();
    save.reset();
  };
  const changeQuestion = (value: string) => {
    setQuestion(value);
    preview.reset();
  };
  const reset = () => {
    if (!loaded.data) return;
    setSettings(loaded.data.settings);
    setPrompt(loaded.data.system_prompt);
    preview.reset();
    save.reset();
  };

  const previewSourceTitles = [
    ...new Set((preview.data?.sources ?? []).map((source) => source.title)),
  ];

  if (loaded.isLoading) {
    return (
      <Card className="grid min-h-80 place-items-center text-sm text-muted">
        Loading AI settings…
      </Card>
    );
  }
  if (loaded.isError) {
    return (
      <Card className="grid min-h-80 place-items-center text-center">
        <div>
          <Warning className="mx-auto text-danger" />
          <h2 className="mt-3 font-semibold">Unable to load AI settings</h2>
          <p className="mt-2 text-sm text-muted">
            The saved assistant configuration could not be retrieved.
          </p>
          <Button className="mt-5" tone="secondary" onClick={() => loaded.refetch()}>
            <ArrowsClockwise size={18} />
            Try again
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid items-start gap-5 xl:grid-cols-[1.05fr_.95fr]">
        <Card className="overflow-hidden p-0">
          <div className="border-b border-line px-5 py-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold">Assistant controls</h2>
                <p className="mt-1 text-sm text-muted">
                  Answer style, sources, and document indexing.
                </p>
              </div>
              <Badge tone={dirty ? "warning" : "success"}>{dirty ? "Unsaved" : "Saved"}</Badge>
            </div>
          </div>
          <div className="divide-y divide-line">
            {controls.map((control) => (
              <SettingToggle
                key={control.key}
                label={control.label}
                copy={control.copy}
                checked={settings[control.key]}
                onChange={(checked) => changeSetting(control.key, checked)}
              />
            ))}
          </div>
        </Card>

        <Card className="flex flex-col">
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
              <Play size={18} />
            </div>
            <div>
              <h2 className="text-sm font-semibold">Test before applying</h2>
              <p className="mt-1 text-sm leading-6 text-muted">
                Preview an answer using your current changes and company documents.
              </p>
            </div>
          </div>
          <label className="mt-5 block text-sm font-medium">
            Test question
            <textarea
              className={`${fieldClass} mt-2 min-h-24 resize-none`}
              value={question}
              onChange={(event) => changeQuestion(event.target.value)}
              placeholder="Ask a realistic employee question…"
            />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="focus-ring rounded px-1 py-1 text-sm text-muted hover:text-accent"
              onClick={() => changeQuestion("When are salaries paid?")}
            >
              Payroll example
            </button>
            <span className="text-line">·</span>
            <button
              type="button"
              className="focus-ring rounded px-1 py-1 text-sm text-muted hover:text-accent"
              onClick={() => changeQuestion("How do I request VPN access?")}
            >
              IT example
            </button>
          </div>
          <Button
            className="mt-4 self-start"
            onClick={() => preview.mutate()}
            disabled={!question.trim() || !prompt.trim() || preview.isPending}
          >
            <Play size={18} />
            {preview.isPending ? "Running preview…" : "Run test"}
          </Button>
          {preview.isError && (
            <p className="mt-4 rounded-lg bg-danger/10 p-3 text-sm text-danger">
              {preview.error instanceof Error ? preview.error.message : "Preview failed"}
            </p>
          )}
          {preview.data ? (
            <div className="mt-5 rounded-lg border border-line bg-ink p-4" aria-live="polite">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">Preview response</p>
                <span className="text-xs text-muted">
                  {preview.data.latency_ms} ms ·{" "}
                  {settings.show_sources
                    ? `${preview.data.sources.length} sources`
                    : "sources hidden"}
                </span>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{preview.data.answer}</p>
              {previewSourceTitles.length > 0 && (
                <div className="mt-4 border-t border-line pt-4 text-xs text-muted">
                  Evidence: {previewSourceTitles.slice(0, 2).join(" · ")}
                </div>
              )}
            </div>
          ) : (
            <div className="mt-5 grid min-h-36 place-items-center rounded-lg border border-dashed border-line bg-ink p-5 text-center">
              <div>
                <Play className="mx-auto text-muted" size={20} />
                <p className="mt-2 text-sm font-medium">Preview appears here</p>
                <p className="mt-1 text-sm text-muted">
                  Run a test to see your changes in a response.
                </p>
              </div>
            </div>
          )}
        </Card>
      </div>

      <details className="group rounded-lg border border-line bg-panel">
        <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-4 rounded-lg px-5 py-4">
          <div>
            <p className="text-sm font-semibold">System prompt</p>
            <p className="mt-1 text-sm text-muted">
              The core instruction applied to grounded answer generation.
            </p>
          </div>
          <SlidersHorizontal className="text-muted transition group-open:rotate-90" size={18} />
        </summary>
        <div className="border-t border-line p-5">
          <div className="mb-3 flex items-center justify-between gap-3">
            <span className="text-xs text-muted">{prompt.length} characters</span>
            <Button
              tone="ghost"
              onClick={() => loaded.data && changePrompt(loaded.data.default_system_prompt)}
            >
              <ArrowCounterClockwise size={18} />
              Reset to default
            </Button>
          </div>
          <textarea
            className={`${fieldClass} min-h-56 font-mono text-xs leading-6`}
            aria-label="System prompt"
            value={prompt}
            onChange={(event) => changePrompt(event.target.value)}
          />
          <p className="mt-3 text-xs leading-5 text-muted">
            Use the preview before applying. A weak prompt can reduce grounding quality even when
            the documents are correct.
          </p>
        </div>
      </details>

      {(save.isError || save.isSuccess || dirty) && (
        <div
          className="sticky bottom-4 z-10 flex flex-col gap-3 rounded-lg border border-line bg-panel p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
          aria-live="polite"
        >
          <div>
            <p className={`text-sm font-semibold ${save.isError ? "text-danger" : ""}`}>
              {save.isError
                ? "Settings were not applied"
                : save.isSuccess && !dirty
                  ? "Settings applied"
                  : "You have unsaved changes"}
            </p>
            <p className="mt-1 text-xs text-muted">
              {save.isError
                ? save.error instanceof Error
                  ? save.error.message
                  : "Try again after checking the API connection."
                : "Changes apply to new answers."}
            </p>
          </div>
          <div className="flex gap-2">
            <Button tone="secondary" onClick={reset} disabled={!dirty}>
              <ArrowCounterClockwise size={18} />
              Discard
            </Button>
            <Button
              onClick={() => save.mutate()}
              disabled={!dirty || !prompt.trim() || save.isPending}
            >
              <FloppyDisk size={18} />
              {save.isPending ? "Applying…" : "Apply settings"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function SettingToggle({
  label,
  copy,
  checked,
  onChange,
}: {
  label: string;
  copy: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-5 px-5 py-4">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="mt-1 max-w-lg text-sm leading-6 text-muted">{copy}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`focus-ring relative h-6 w-11 shrink-0 rounded-full border transition ${checked ? "border-accent bg-accent" : "border-line bg-raised"}`}
      >
        <span
          className={`absolute top-0.5 h-4.5 w-4.5 rounded-full shadow-sm transition-all ${checked ? "left-[21px] bg-on-accent" : "left-0.5 bg-muted"}`}
        />
      </button>
    </div>
  );
}
