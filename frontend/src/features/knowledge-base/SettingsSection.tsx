import { AlertTriangle, Play, RefreshCw, RotateCcw, Save, Settings2 } from "lucide-react";
import type { AISettings } from "../../api/types";
import { Badge, Button, Card, LoadingSkeleton, fieldClass } from "../../components/ui";
import { useUnsavedChanges } from "../../components/UnsavedChanges";
import { useAISettings } from "./useKnowledge";
import { MessageContent } from "../../components/MessageContent";

const controls: { key: keyof AISettings; label: string; copy: string }[] = [
  { key: "strict_grounding", label: "Use reliable sources only", copy: "Answer only when company documents provide reliable evidence." },
  { key: "concise_answers", label: "Keep answers concise", copy: "Prefer short, scannable answers over long explanations." },
  { key: "ask_clarifying_questions", label: "Ask clarifying questions", copy: "Ask for missing details instead of guessing what an employee needs." },
  { key: "suggest_next_steps", label: "Suggest next steps", copy: "Include a practical next action when appropriate." },
  { key: "show_sources", label: "Show sources", copy: "Let employees inspect the document evidence behind an answer." },
  { key: "auto_index_uploads", label: "Process new documents automatically", copy: "Make uploaded documents searchable without a separate indexing step." },
];
const groups: {label: string; keys: (keyof AISettings)[]}[] = [
  {label: "Sources and accuracy", keys: ["strict_grounding", "show_sources"]},
  {label: "Response style", keys: ["concise_answers", "ask_clarifying_questions", "suggest_next_steps"]},
  {label: "Document processing", keys: ["auto_index_uploads"]},
];

export function SettingsSection() {
  const { loaded, settings, prompt, question, dirty, save, preview, changeSetting, changePrompt, changeQuestion, reset, previewSourceTitles } = useAISettings();
  useUnsavedChanges(dirty);
  if (loaded.isLoading) return <Card><LoadingSkeleton label="Loading AI settings…"/></Card>;
  if (loaded.isError && !loaded.data) return <Card><div role="alert" className="space-y-3"><AlertTriangle className="text-danger" aria-hidden="true"/><h2 className="font-semibold">Unable to load AI settings</h2><p className="text-sm text-muted">The saved configuration is unavailable. Check the connection and try again.</p><Button tone="secondary" onClick={() => void loaded.refetch()}><RefreshCw size={16} aria-hidden="true"/>Retry settings</Button></div></Card>;

  return <div className="space-y-4">
    {loaded.isError && <div role="alert" className="rounded-lg border border-danger/25 p-4 text-sm"><p className="text-danger">The latest settings could not be loaded. Your unsaved changes are still here.</p><Button tone="secondary" className="mt-3" onClick={() => void loaded.refetch()}>Retry settings</Button></div>}
    <section aria-label="Save assistant settings" className="knowledge-settings-commandbar">
      <div className={`knowledge-settings-state${save.isSuccess && !dirty ? " success-feedback" : ""}`} role={!save.isError && (save.isSuccess || dirty) ? "status" : undefined}>
        <Badge tone={save.isError ? "danger" : dirty ? "warning" : "success"}>{save.isError ? "Not applied" : save.isSuccess && !dirty ? "Settings applied" : dirty ? "Unsaved changes" : "Saved"}</Badge>
      </div>
      <div className="knowledge-settings-actions"><Button tone="secondary" onClick={reset} disabled={!dirty || save.isPending || preview.isPending}>Discard</Button><Button onClick={() => save.mutate()} disabled={!dirty || !prompt.trim() || save.isPending || preview.isPending}><Save size={15} aria-hidden="true"/>{save.isPending ? "Applying…" : "Apply settings"}</Button></div>
    </section>
    {save.isError && <p role="alert" className="rounded-lg border border-danger/25 bg-danger/5 p-3 text-sm text-danger">Settings were not applied. {save.error instanceof Error ? save.error.message : "Check the connection and try again."}</p>}
    <nav className="knowledge-section-links" aria-label="AI settings sections"><a className="focus-ring" href="#answer-preferences">Preferences</a><a className="focus-ring" href="#answer-preview">Test answer</a><a className="focus-ring" href="#advanced-instructions">Instructions</a></nav>
    <div className="knowledge-settings-grid">
      <section id="answer-preferences" aria-labelledby="answer-preferences-title">
      <Card padding="none">
        <div className="border-b border-line px-4 py-3"><h2 id="answer-preferences-title" className="text-base font-semibold">Answer preferences</h2><p className="mt-1 text-xs leading-5 text-muted">Changes apply to future answers after you save.</p></div>
        <div>{groups.map(group => <fieldset key={group.label} className="knowledge-preference-group" disabled={save.isPending || preview.isPending}>
          <legend>{group.label}</legend>
          {controls.filter(control => group.keys.includes(control.key)).map(control => <label key={control.key} className="knowledge-preference-row">
            <input type="checkbox" className="focus-ring h-5 w-5 shrink-0 accent-lime" checked={settings[control.key]} onChange={event => changeSetting(control.key, event.target.checked)}/>
            <span className="min-w-0"><span className="block text-sm font-medium">{control.label}</span><span className="mt-0.5 block text-xs leading-5 text-muted">{control.copy}</span></span>
          </label>)}
        </fieldset>)}</div>
      </Card>
      </section>
      <section id="answer-preview" aria-labelledby="answer-preview-title">
      <Card className="min-w-0 space-y-4">
        <div className="knowledge-preview-header"><Play size={20} className="mt-0.5 shrink-0 text-muted" aria-hidden="true"/><div><h2 id="answer-preview-title" className="text-base font-semibold">Test before applying</h2><p className="mt-1 text-xs leading-5 text-muted">Preview an answer using these preferences and company sources. The test calls the AI service; it does not save a chat.</p></div></div>
        <label className="block text-sm font-medium">Test question<textarea className={`${fieldClass} mt-2 min-h-24 resize-y`} value={question} onChange={event => changeQuestion(event.target.value)} placeholder="Ask a realistic employee question…" disabled={preview.isPending || save.isPending}/></label>
        <div className="knowledge-preview-controls"><div className="knowledge-preview-examples"><Button tone="ghost" onClick={() => changeQuestion("When are salaries paid?")} disabled={preview.isPending}>Payroll example</Button><Button tone="ghost" onClick={() => changeQuestion("How do I request VPN access?")} disabled={preview.isPending}>IT example</Button></div>
        <Button tone="secondary" onClick={() => preview.mutate()} disabled={!question.trim() || !prompt.trim() || preview.isPending || save.isPending}><Play size={16} aria-hidden="true"/>{preview.isPending ? "Running preview…" : "Run test"}</Button>
        </div>
        <p role="status" aria-atomic="true" className={preview.isPending ? "text-sm text-muted" : "sr-only"}>{preview.isPending ? "Waiting for the preview answer…" : preview.isSuccess ? "Preview ready. Review the response below." : ""}</p>
        {preview.isError && <p role="alert" className="rounded-lg bg-danger/10 p-3 text-sm text-danger">{preview.error instanceof Error ? preview.error.message : "Preview failed. Check the connection and try again."}</p>}
        {preview.data ? <section className="min-w-0 rounded-lg border border-line bg-ink/50 p-4" aria-label="Preview response"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Preview response</h3><span className="text-xs text-muted">{settings.show_sources ? `${preview.data.sources.length} source passages` : "Sources hidden"}</span></div><div className="mt-3"><MessageContent content={preview.data.answer}/></div>{previewSourceTitles.length > 0 && <p className="mt-4 border-t border-line pt-3 text-xs leading-5 text-muted [overflow-wrap:anywhere]">Sources: {previewSourceTitles.join(" · ")}</p>}</section> : !preview.isPending && !preview.isError && <p className="rounded-lg border border-dashed border-line p-4 text-sm leading-6 text-muted">Choose a sample question or enter your own, then run a test to inspect the answer before applying changes.</p>}
      </Card>
      </section>
    </div>
    <details id="advanced-instructions" className="knowledge-advanced group rounded-lg border border-line bg-panel">
      <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-4 rounded-xl p-4 sm:p-5"><span><span className="block font-semibold">Advanced instructions</span><span className="mt-1 block text-sm text-muted">Edit the system prompt used to generate answers.</span></span><Settings2 className="shrink-0 text-muted" size={18} aria-hidden="true"/></summary>
      <div className="space-y-3 border-t border-line p-4 sm:p-5"><div className="flex flex-wrap items-center justify-between gap-3"><label htmlFor="system-prompt" className="text-sm font-semibold">System prompt</label><Button tone="ghost" disabled={save.isPending || preview.isPending} onClick={() => loaded.data && changePrompt(loaded.data.default_system_prompt)}><RotateCcw size={15} aria-hidden="true"/>Reset to default</Button></div><textarea id="system-prompt" aria-describedby="system-prompt-help" className={`${fieldClass} min-h-48 font-mono text-sm leading-6`} value={prompt} disabled={save.isPending || preview.isPending} onChange={event => changePrompt(event.target.value)}/><p id="system-prompt-help" className="text-xs leading-5 text-muted">{prompt.length} characters. Keep instructions consistent with company policies. Test the result before applying.</p></div>
    </details>
  </div>;
}



