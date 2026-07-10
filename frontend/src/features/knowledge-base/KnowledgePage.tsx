import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  CheckCircle2,
  Download,
  FileText,
  FileUp,
  MessageSquareWarning,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, downloadFile } from "../../api/client";
import type { AISettings, AISettingsResponse, AISettingsTestResult, DocumentItem, FeedbackItem, KnowledgeGap, Metrics } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Badge, Button, Card, Drawer, Hint, fieldClass, statusTone } from "../../components/ui";

type Section = "overview" | "documents" | "quality" | "settings";

const navigation: [Section, string, ReactNode][] = [
  ["overview", "Overview", <BarChart3 />],
  ["documents", "Documents", <BookOpen />],
  ["quality", "Quality", <MessageSquareWarning />],
  ["settings", "AI settings", <Settings2 />],
];

export function KnowledgePage() {
  const { token } = useAuth();
  const [section, setSection] = useState<Section>("overview");
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<{ metrics: Metrics }>("/api/v1/admin/metrics", token),
  });
  const sidebar = <nav className="space-y-1">
    {navigation.map(([id, label, icon]) => <button
      key={id}
      onClick={() => setSection(id)}
      className={`focus-ring flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm ${section === id ? "bg-lime-soft text-lime" : "text-muted hover:bg-raised hover:text-cream"} [&>svg]:h-4 [&>svg]:w-4`}
    >{icon}{label}</button>)}
  </nav>;
  const title = navigation.find(item => item[0] === section)?.[1] ?? "Knowledge operations";

  return <Shell sidebar={sidebar} eyebrow="Knowledge operations">
    <div className="mx-auto max-w-7xl p-4 sm:p-8">
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.18em] text-lime">Knowledge health</p>
          <h1 className="mt-3 text-4xl font-medium tracking-[-.035em]">{title}</h1>
        </div>
        {section === "overview" && <Button tone="secondary" onClick={() => metrics.refetch()}><RefreshCw size={15} />Refresh</Button>}
      </div>
      {section === "overview" && <Overview metrics={metrics.data?.metrics} />}
      {section === "documents" && <Documents />}
      {section === "quality" && <Quality metrics={metrics.data?.metrics} onNavigate={setSection} />}
      {section === "settings" && <Settings />}
    </div>
  </Shell>;
}

function Overview({ metrics: value }: { metrics?: Metrics }) {
  const cards = [
    ["Questions", value?.questions ?? 0, "All assistant conversations", <BarChart3 />],
    ["Grounded rate", `${value?.grounded_answer_rate ?? 0}%`, "Answers with document evidence", <CheckCircle2 />],
    ["Unanswered", value?.unanswered_questions ?? 0, "Knowledge gaps to resolve", <AlertTriangle />],
    ["Positive feedback", `${value?.positive_feedback_rate ?? 0}%`, "Helpful response ratings", <ThumbsUp />],
    ["Requests created", value?.requests_created ?? 0, "Employee actions started", <FileText />],
    ["Approved", value?.requests_approved ?? 0, "Requests approved by managers", <CheckCircle2 />],
  ];
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
    {cards.map(([label, metric, copy, icon]) => <Card key={String(label)} className="min-h-40">
      <div className="flex items-start justify-between"><span className="text-sm font-semibold">{label}</span><span className="text-lime [&>svg]:h-5 [&>svg]:w-5">{icon}</span></div>
      <strong className="mt-7 block text-4xl font-medium tracking-tight">{metric}</strong>
      <p className="mt-2 text-xs text-muted">{copy}</p>
    </Card>)}
  </div>;
}

function Documents() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<{ documents: DocumentItem[] }>("/api/v1/documents", token),
  });
  const list = documents.data?.documents ?? [];
  const stats = {
    indexed: list.filter(item => item.index_status === "indexed").length,
    pending: list.filter(item => ["pending", "indexing"].includes(item.index_status)).length,
    errors: list.filter(item => item.index_status === "error").length,
  };
  const indexing = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}/index`, token, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });
  const removing = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}`, token, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
  const download = async (document: DocumentItem) => {
    setDownloadError("");
    try {
      await downloadFile(`/api/v1/documents/${document.id}/download`, token, document.name.split("/").pop() ?? document.name);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Unable to download the document");
    }
  };

  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-3">
      <DocumentMetric label="Indexed" value={stats.indexed} copy="Ready for grounded answers" tone="success" />
      <DocumentMetric label="Pending" value={stats.pending} copy="Waiting for indexing" tone="warning" />
      <DocumentMetric label="Errors" value={stats.errors} copy="Need administrator attention" tone="danger" />
    </div>
    <Card className="overflow-hidden p-0">
      <div className="flex flex-col gap-4 border-b border-line p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-semibold">Source library</h2>
          <p className="mt-1 text-xs text-muted">Upload, inspect, index, and retire the documents behind every grounded answer.</p>
        </div>
        <div className="flex gap-2">
          <Button tone="secondary" onClick={() => documents.refetch()}><RefreshCw size={15} />Refresh</Button>
          <Button onClick={() => setUploadOpen(true)}><Upload size={16} />Add document</Button>
        </div>
      </div>
      {downloadError && <p className="m-4 rounded-xl bg-danger/10 p-3 text-sm text-danger">{downloadError}</p>}
      {documents.isLoading && <div className="grid min-h-48 place-items-center text-sm text-muted">Loading source library…</div>}
      {documents.isError && <div className="grid min-h-48 place-items-center text-sm text-danger">Unable to load documents.</div>}
      {!documents.isLoading && !list.length && <Empty title="No documents yet" copy="Upload the first policy or handbook to create the knowledge base." />}
      <div className="divide-y divide-line">
        {list.map(document => <div key={document.id} className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(150px,.7fr)_90px_155px_auto] lg:items-center">
          <div className="min-w-0">
            <div className="flex items-center gap-2"><FileText size={16} className="shrink-0 text-coral" /><strong className="truncate text-sm">{document.title}</strong></div>
            <p className="mt-1 truncate text-xs text-muted">{document.name} · {formatBytes(document.size)}</p>
            {document.index_error && <p className="mt-2 text-xs leading-5 text-danger">{document.index_error}</p>}
          </div>
          <div><span className="text-[10px] uppercase text-muted">Category</span><p className="mt-1 text-sm">{document.category} · v{document.version}</p></div>
          <div><span className="text-[10px] uppercase text-muted">Chunks</span><p className="mt-1 text-sm font-semibold">{document.chunk_count}</p></div>
          <div><Badge tone={statusTone(document.index_status)}>{document.index_status}</Badge><p className="mt-2 text-[10px] text-muted">{document.indexed_at ? new Date(document.indexed_at).toLocaleString() : "Never indexed"}</p></div>
          <div className="flex items-center justify-end gap-1">
            <Hint label="Download document"><Button tone="ghost" aria-label={`Download ${document.title}`} className="h-10 w-10" style={{ padding: 0 }} onClick={() => download(document)}><Download size={17} /></Button></Hint>
            <Button tone="secondary" onClick={() => indexing.mutate(document.id)} disabled={indexing.isPending}>{document.index_status === "indexed" ? "Re-index" : "Index"}</Button>
            <Hint label="Delete document"><Button tone="ghost" aria-label={`Delete ${document.title}`} className="h-10 w-10 text-danger" style={{ padding: 0 }} onClick={() => setDeleteTarget(document)}><Trash2 size={17} /></Button></Hint>
          </div>
        </div>)}
      </div>
    </Card>
    {indexing.isError && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{indexing.error instanceof Error ? indexing.error.message : "Indexing failed"}</p>}
    <UploadDocumentDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    <Drawer open={Boolean(deleteTarget)} onOpenChange={open => !open && setDeleteTarget(null)} title="Remove document?" description="This action also rebuilds the knowledge index so the assistant stops using this source." placement="center">
      {deleteTarget && <div className="space-y-5">
        <Card className="bg-ink/50"><p className="text-xs uppercase tracking-wider text-muted">Document</p><p className="mt-2 font-semibold">{deleteTarget.title}</p><p className="mt-1 text-xs text-muted">{deleteTarget.name}</p></Card>
        <div className="rounded-2xl border border-danger/25 bg-danger/10 p-4 text-sm leading-6 text-cream">Deleting an outdated source is permanent. Future answers will no longer retrieve evidence from it.</div>
        {removing.isError && <p className="text-sm text-danger">{removing.error instanceof Error ? removing.error.message : "Deletion failed"}</p>}
        <div className="flex justify-end gap-3"><Button tone="secondary" onClick={() => setDeleteTarget(null)}>Keep document</Button><Button tone="danger" onClick={() => removing.mutate(deleteTarget.id)} disabled={removing.isPending}><Trash2 size={16} />{removing.isPending ? "Removing…" : "Remove and rebuild"}</Button></div>
      </div>}
    </Drawer>
  </div>;
}

function DocumentMetric({ label, value, copy, tone }: { label: string; value: number; copy: string; tone: "success" | "warning" | "danger" }) {
  const color = tone === "success" ? "text-lime" : tone === "warning" ? "text-coral" : "text-danger";
  return <Card className="p-4"><p className="text-[10px] uppercase tracking-wider text-muted">{label}</p><div className="mt-3 flex items-end justify-between gap-3"><strong className={`text-3xl ${color}`}>{value}</strong><p className="pb-1 text-right text-[11px] text-muted">{copy}</p></div></Card>;
}

function UploadDocumentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const aiSettings = useQuery({ queryKey: ["ai-settings"], queryFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token) });
  const autoIndex = aiSettings.data?.settings.auto_index_uploads ?? true;
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a document before uploading.");
      const form = new FormData();
      form.append("file", file);
      return api<{ document: DocumentItem }>("/api/v1/documents", token, { method: "POST", body: form });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      setFile(null);
      onOpenChange(false);
    },
  });
  return <Drawer open={open} onOpenChange={onOpenChange} title="Add a knowledge document" description="Supported files become private sources for grounded assistant answers." placement="center">
    <div className="space-y-5">
      <label className="focus-ring grid min-h-44 cursor-pointer place-items-center rounded-2xl border border-dashed border-line bg-ink/40 p-6 text-center transition hover:border-lime/40 hover:bg-lime-soft/30">
        <input className="sr-only" type="file" accept=".md,.txt,.pdf,.docx" onChange={event => setFile(event.target.files?.[0] ?? null)} />
        <div><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-lime-soft text-lime"><FileUp size={22} /></div><p className="mt-4 text-sm font-semibold">Choose a document</p><p className="mt-2 text-xs text-muted">Markdown, TXT, PDF, or DOCX · maximum 10 MB</p></div>
      </label>
      {file && <Card className="flex items-center justify-between gap-4 bg-ink/50 p-4"><div className="min-w-0"><p className="truncate text-sm font-semibold">{file.name}</p><p className="mt-1 text-xs text-muted">{formatBytes(file.size)}</p></div><Badge tone="warning">Ready to upload</Badge></Card>}
      <div className="flex items-start justify-between gap-4 rounded-xl border border-line p-4"><span><strong className="block text-sm">Automatic indexing</strong><span className="mt-1 block text-xs leading-5 text-muted">Controlled globally from AI settings. {autoIndex ? "This upload will be indexed immediately." : "This upload will wait for manual indexing."}</span></span><Badge tone={autoIndex ? "success" : "neutral"}>{autoIndex ? "On" : "Off"}</Badge></div>
      {upload.isError && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{upload.error instanceof Error ? upload.error.message : "Upload failed"}</p>}
      <div className="flex justify-end gap-3"><Button tone="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={() => upload.mutate()} disabled={!file || upload.isPending}><Upload size={16} />{upload.isPending ? (autoIndex ? "Uploading and indexing…" : "Uploading…") : "Add document"}</Button></div>
    </div>
  </Drawer>;
}

function Quality({ metrics, onNavigate }: { metrics?: Metrics; onNavigate: (section: Section) => void }) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"negative" | "gaps" | "positive">("negative");
  const [search, setSearch] = useState("");
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [selectedGap, setSelectedGap] = useState<KnowledgeGap | null>(null);
  const feedback = useQuery({ queryKey: ["admin-feedback"], queryFn: () => api<{ feedback: FeedbackItem[] }>("/api/v1/admin/feedback?sentiment=all&limit=500", token) });
  const gaps = useQuery({ queryKey: ["knowledge-gaps"], queryFn: () => api<{ questions: KnowledgeGap[] }>("/api/v1/admin/unanswered", token) });
  const reviewGap = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "resolved" | "ignored" }) => api(`/api/v1/admin/quality/${id}`, token, { method: "POST", body: JSON.stringify({ action }) }),
    onSuccess: () => {
      setSelectedGap(null);
      queryClient.invalidateQueries({ queryKey: ["knowledge-gaps"] });
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
  const feedbackItems = feedback.data?.feedback ?? [];
  const gapItems = gaps.data?.questions ?? [];
  const counts = {
    positive: feedbackItems.filter(item => item.sentiment === "positive").length,
    negative: feedbackItems.filter(item => item.sentiment === "negative").length,
    gaps: gapItems.length,
  };
  const needle = search.trim().toLowerCase();
  const visibleFeedback = feedbackItems.filter(item => item.sentiment === mode && (!needle || `${item.question} ${item.answer} ${item.comment}`.toLowerCase().includes(needle)));
  const visibleGaps = gapItems.filter(item => !needle || `${item.question} ${item.assistant}`.toLowerCase().includes(needle));
  const loading = feedback.isLoading || gaps.isLoading;
  const empty = mode === "gaps" ? !visibleGaps.length : !visibleFeedback.length;

  return <div className="space-y-5">
    <div className="grid gap-3 md:grid-cols-3">
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Helpful rate</p><strong className="mt-4 block text-4xl text-lime">{metrics?.positive_feedback_rate ?? 0}%</strong><p className="mt-2 text-xs text-muted">Share of all ratings marked helpful</p></Card>
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Needs review</p><strong className="mt-4 block text-4xl text-danger">{counts.negative}</strong><p className="mt-2 text-xs text-muted">Rated answers that may need a fix</p></Card>
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Knowledge gaps</p><strong className="mt-4 block text-4xl text-coral">{counts.gaps}</strong><p className="mt-2 text-xs text-muted">Workplace questions with no reliable source</p></Card>
    </div>
    <Card className="overflow-hidden p-0">
      <div className="border-b border-line p-5">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div><h2 className="font-semibold">Answer quality queue</h2><p className="mt-1 text-xs text-muted">Review rated answers and real knowledge gaps. Out-of-scope noise is excluded automatically.</p></div>
          <Button tone="secondary" onClick={() => { feedback.refetch(); gaps.refetch(); }}><RefreshCw size={15} />Refresh</Button>
        </div>
        <div className="mt-5 flex flex-col gap-3 xl:flex-row">
          <div className="grid grid-cols-3 rounded-xl border border-line bg-ink p-1">
            <QualityTab active={mode === "negative"} tone="danger" onClick={() => setMode("negative")}><ThumbsDown size={14} />Needs review · {counts.negative}</QualityTab>
            <QualityTab active={mode === "gaps"} tone="warning" onClick={() => setMode("gaps")}><AlertTriangle size={14} />Knowledge gaps · {counts.gaps}</QualityTab>
            <QualityTab active={mode === "positive"} tone="success" onClick={() => setMode("positive")}><ThumbsUp size={14} />Helpful · {counts.positive}</QualityTab>
          </div>
          <label className="relative flex-1"><Search className="absolute left-3 top-3 text-muted" size={17} /><input className={`${fieldClass} pl-10`} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search questions, answers, or notes" /></label>
        </div>
      </div>
      {loading && <div className="grid min-h-56 place-items-center text-sm text-muted">Loading quality signals…</div>}
      {!loading && empty && <Empty title={mode === "negative" ? "No answers need review" : mode === "gaps" ? "No active knowledge gaps" : "No helpful examples yet"} copy={search ? "Try a different search." : "New quality signals will appear here automatically."} />}
      <div className="divide-y divide-line">
        {mode === "gaps" ? visibleGaps.map(item => <button key={item.id} onClick={() => setSelectedGap(item)} className="focus-ring grid w-full gap-4 p-5 text-left transition hover:bg-raised/60 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_140px]">
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-coral">Unanswered workplace question</p><p className="mt-2 line-clamp-3 text-sm font-semibold leading-6">{item.question}</p></div>
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-muted">Assistant response</p><p className="mt-2 line-clamp-3 text-sm leading-6 text-muted">{item.assistant}</p></div>
          <div className="lg:text-right"><Badge tone="warning">Knowledge gap</Badge><p className="mt-2 text-[10px] text-muted">{new Date(item.timestamp).toLocaleString()}</p></div>
        </button>) : visibleFeedback.map(item => <button key={item.id} onClick={() => setSelectedFeedback(item)} className="focus-ring grid w-full gap-4 p-5 text-left transition hover:bg-raised/60 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_140px]">
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-coral">Employee question</p><p className="mt-2 line-clamp-3 text-sm font-semibold leading-6">{item.question || "Question was not captured"}</p></div>
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-muted">AI answer</p><p className="mt-2 line-clamp-3 text-sm leading-6 text-muted">{item.answer || "Answer was not captured for this older feedback signal."}</p>{item.comment && <p className="mt-3 line-clamp-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-cream">“{item.comment}”</p>}</div>
          <div className="flex items-start justify-between gap-3 lg:block lg:text-right"><Badge tone={item.sentiment === "positive" ? "success" : "danger"}>{item.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><p className="mt-2 text-[10px] text-muted">{new Date(item.created_at).toLocaleString()}</p><p className="mt-2 text-[10px] uppercase tracking-wider text-muted">Anonymous</p></div>
        </button>)}
      </div>
    </Card>
    <Drawer open={Boolean(selectedFeedback)} onOpenChange={open => !open && setSelectedFeedback(null)} title="Response feedback" description="An anonymized view of the exact exchange the employee rated." placement="center">
      {selectedFeedback && <div className="space-y-5"><div className="flex items-center justify-between"><Badge tone={selectedFeedback.sentiment === "positive" ? "success" : "danger"}>{selectedFeedback.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><span className="flex items-center gap-2 text-xs text-muted"><ShieldCheck size={15} />Anonymous</span></div><ConversationBlock label="Employee question" text={selectedFeedback.question || "Question was not captured."} accent="coral" /><ConversationBlock label="PeopleFlow answer" text={selectedFeedback.answer || "Answer was not captured for this older feedback signal."} accent="lime" />{selectedFeedback.comment && <section className="rounded-2xl border border-danger/25 bg-danger/10 p-5"><p className="text-[10px] font-bold uppercase tracking-wider text-danger">Employee note</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{selectedFeedback.comment}</p></section>}<p className="text-right text-xs text-muted">Received {new Date(selectedFeedback.created_at).toLocaleString()}</p></div>}
    </Drawer>
    <Drawer open={Boolean(selectedGap)} onOpenChange={open => !open && setSelectedGap(null)} title="Knowledge gap" description="A supported workplace question that could not be grounded in the current source library." placement="center">
      {selectedGap && <div className="space-y-5"><Badge tone="warning">Needs a source</Badge><ConversationBlock label="Employee question" text={selectedGap.question} accent="coral" /><ConversationBlock label="PeopleFlow response" text={selectedGap.assistant} accent="lime" />{reviewGap.isError && <p className="text-sm text-danger">{reviewGap.error instanceof Error ? reviewGap.error.message : "Unable to update this item"}</p>}<div className="flex flex-wrap justify-end gap-3"><Button tone="ghost" onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "ignored" })} disabled={reviewGap.isPending}>Ignore</Button><Button tone="secondary" onClick={() => { setSelectedGap(null); onNavigate("documents"); }}><BookOpen size={16} />Add source</Button><Button onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "resolved" })} disabled={reviewGap.isPending}><CheckCircle2 size={16} />Mark resolved</Button></div></div>}
    </Drawer>
  </div>;
}

function QualityTab({ active, tone, onClick, children }: { active: boolean; tone: "danger" | "warning" | "success"; onClick: () => void; children: ReactNode }) {
  const activeClass = tone === "danger" ? "bg-danger/15 text-danger" : tone === "warning" ? "bg-coral/15 text-coral" : "bg-lime-soft text-lime";
  return <button onClick={onClick} className={`focus-ring flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ${active ? activeClass : "text-muted hover:text-cream"}`}>{children}</button>;
}

function ConversationBlock({ label, text, accent }: { label: string; text: string; accent: "coral" | "lime" }) {
  return <section className="rounded-2xl border border-line bg-ink/50 p-5"><p className={`text-[10px] font-bold uppercase tracking-wider ${accent === "coral" ? "text-coral" : "text-lime"}`}>{label}</p><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-cream">{text}</p></section>;
}

function Settings() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const defaults: AISettings = { strict_grounding: true, concise_answers: true, ask_clarifying_questions: true, suggest_next_steps: true, show_sources: true, auto_index_uploads: true };
  const [settings, setSettings] = useState<AISettings>(defaults);
  const [prompt, setPrompt] = useState("");
  const [question, setQuestion] = useState("When are salaries paid?");
  const loaded = useQuery({ queryKey: ["ai-settings"], queryFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token) });
  useEffect(() => {
    if (loaded.data) {
      setSettings(loaded.data.settings);
      setPrompt(loaded.data.system_prompt);
    }
  }, [loaded.data]);
  const dirty = loaded.data
    ? JSON.stringify(settings) !== JSON.stringify(loaded.data.settings) || prompt !== loaded.data.system_prompt
    : false;
  const save = useMutation({
    mutationFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token, { method: "PUT", body: JSON.stringify({ settings, system_prompt: prompt }) }),
    onSuccess: data => {
      queryClient.setQueryData(["ai-settings"], data);
    },
  });
  const preview = useMutation({
    mutationFn: () => api<AISettingsTestResult>("/api/v1/admin/ai-settings/test", token, { method: "POST", body: JSON.stringify({ question, settings, system_prompt: prompt }) }),
  });
  const changeSetting = (key: keyof AISettings, checked: boolean) => {
    setSettings(current => ({ ...current, [key]: checked }));
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
  const controls: { key: keyof AISettings; label: string; copy: string }[] = [
    { key: "strict_grounding", label: "Strict grounding", copy: "Answer only when company sources provide reliable evidence." },
    { key: "concise_answers", label: "Concise answers", copy: "Prefer short, scannable responses over long explanations." },
    { key: "ask_clarifying_questions", label: "Ask clarifying questions", copy: "Request missing context instead of guessing employee intent." },
    { key: "suggest_next_steps", label: "Suggest next steps", copy: "End useful answers with one practical action when appropriate." },
    { key: "show_sources", label: "Show sources", copy: "Expose supporting document evidence in the employee chat." },
    { key: "auto_index_uploads", label: "Auto-index uploads", copy: "Make new documents searchable immediately after upload." },
  ];
  const previewSourceTitles = [...new Set((preview.data?.sources ?? []).map(source => source.title))];

  if (loaded.isLoading) return <Card className="grid min-h-80 place-items-center text-sm text-muted">Loading AI settings…</Card>;
  if (loaded.isError) return <Card className="grid min-h-80 place-items-center text-center"><div><AlertTriangle className="mx-auto text-danger" /><h2 className="mt-3 font-semibold">Unable to load AI settings</h2><p className="mt-2 text-sm text-muted">The saved assistant configuration could not be retrieved.</p><Button className="mt-5" tone="secondary" onClick={() => loaded.refetch()}><RefreshCw size={15} />Try again</Button></div></Card>;

  return <div className="space-y-5">
    <div className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
      <Card className="p-0 overflow-hidden">
        <div className="border-b border-line p-5"><div className="flex items-center justify-between gap-4"><div><h2 className="font-semibold">Assistant controls</h2><p className="mt-1 text-xs text-muted">Six high-impact settings with safe defaults.</p></div><Badge tone={dirty ? "warning" : "success"}>{dirty ? "Unsaved" : "Live"}</Badge></div></div>
        <div className="divide-y divide-line">{controls.map(control => <SettingToggle key={control.key} label={control.label} copy={control.copy} checked={settings[control.key]} onChange={checked => changeSetting(control.key, checked)} />)}</div>
      </Card>
      <Card className="flex min-h-[520px] flex-col border-lime/15 bg-lime-soft/20">
        <div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-lime text-ink"><Play size={17} /></div><div><h2 className="font-semibold">Test before applying</h2><p className="mt-1 text-xs leading-5 text-muted">Runs against the current knowledge base with your unsaved switches and prompt. It creates no request and writes no chat log.</p></div></div>
        <label className="mt-6 block text-xs font-semibold text-muted">Test question<textarea className={`${fieldClass} mt-2 min-h-24 resize-none`} value={question} onChange={event => changeQuestion(event.target.value)} placeholder="Ask a realistic employee question…" /></label>
        <div className="mt-3 flex flex-wrap gap-2"><button className="text-xs text-muted hover:text-cream" onClick={() => changeQuestion("When are salaries paid?")}>Payroll example</button><span className="text-line">·</span><button className="text-xs text-muted hover:text-cream" onClick={() => changeQuestion("How do I request VPN access?")}>IT example</button></div>
        <Button className="mt-5 w-full" onClick={() => preview.mutate()} disabled={!question.trim() || !prompt.trim() || preview.isPending}><Play size={16} />{preview.isPending ? "Running preview…" : "Run test"}</Button>
        {preview.isError && <p className="mt-4 rounded-xl bg-danger/10 p-3 text-sm text-danger">{preview.error instanceof Error ? preview.error.message : "Preview failed"}</p>}
        {preview.data ? <div className="mt-5 flex-1 rounded-2xl border border-line bg-ink/70 p-5"><div className="flex items-center justify-between gap-3"><p className="text-[10px] font-bold uppercase tracking-wider text-lime">Preview response</p><span className="text-[10px] text-muted">{preview.data.latency_ms} ms · {settings.show_sources ? `${preview.data.sources.length} sources` : "sources hidden"}</span></div><p className="mt-4 whitespace-pre-wrap text-sm leading-7">{preview.data.answer}</p>{previewSourceTitles.length > 0 && <div className="mt-4 border-t border-line pt-4 text-xs text-muted">Evidence: {previewSourceTitles.slice(0, 2).join(" · ")}</div>}</div> : <div className="mt-5 grid flex-1 place-items-center rounded-2xl border border-dashed border-line p-6 text-center"><div><Play className="mx-auto text-muted" size={22} /><p className="mt-3 text-sm font-semibold">Preview appears here</p><p className="mt-2 text-xs text-muted">Change a switch, adjust the prompt, and test before saving.</p></div></div>}
      </Card>
    </div>
    <details className="group rounded-2xl border border-line bg-panel">
      <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-4 rounded-2xl p-5"><div><p className="font-semibold">Advanced · System prompt</p><p className="mt-1 text-xs text-muted">The core instruction applied to grounded answer generation.</p></div><Settings2 className="text-muted transition group-open:rotate-90" size={18} /></summary>
      <div className="border-t border-line p-5"><div className="mb-3 flex items-center justify-between gap-3"><span className="text-xs text-muted">{prompt.length} characters</span><Button tone="ghost" onClick={() => loaded.data && changePrompt(loaded.data.default_system_prompt)}><RotateCcw size={14} />Reset to default</Button></div><textarea className={`${fieldClass} min-h-56 font-mono text-xs leading-6`} value={prompt} onChange={event => changePrompt(event.target.value)} /><p className="mt-3 text-xs leading-5 text-muted">Use the preview before applying. A weak prompt can reduce grounding quality even when the documents are correct.</p></div>
    </details>
    {(save.isError || save.isSuccess || dirty) && <div className="sticky bottom-4 z-10 flex flex-col gap-3 rounded-2xl border border-line bg-panel/95 p-4 shadow-2xl backdrop-blur sm:flex-row sm:items-center sm:justify-between"><div><p className={`text-sm font-semibold ${save.isError ? "text-danger" : ""}`}>{save.isError ? "Settings were not applied" : save.isSuccess && !dirty ? "Settings applied" : "Review and apply changes"}</p><p className="mt-1 text-xs text-muted">{save.isError ? (save.error instanceof Error ? save.error.message : "Try again after checking the API connection.") : "New settings affect future answers. Existing feedback and documents stay unchanged."}</p></div><div className="flex gap-2"><Button tone="secondary" onClick={reset} disabled={!dirty}><RotateCcw size={15} />Discard</Button><Button onClick={() => save.mutate()} disabled={!dirty || !prompt.trim() || save.isPending}><Save size={15} />{save.isPending ? "Applying…" : "Apply settings"}</Button></div></div>}
  </div>;
}

function SettingToggle({ label, copy, checked, onChange }: { label: string; copy: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <div className="flex items-center justify-between gap-5 p-5"><div><p className="text-sm font-semibold">{label}</p><p className="mt-1 max-w-lg text-xs leading-5 text-muted">{copy}</p></div><button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={`focus-ring relative h-7 w-12 shrink-0 rounded-full border transition ${checked ? "border-lime/40 bg-lime" : "border-line bg-ink"}`}><span className={`absolute top-1 h-4.5 w-4.5 rounded-full bg-ink transition ${checked ? "left-[25px]" : "left-1 bg-muted"}`} /></button></div>;
}

function Empty({ title, copy }: { title: string; copy: string }) {
  return <div className="grid min-h-56 place-items-center p-6 text-center"><div><CheckCircle2 className="mx-auto text-lime" /><h3 className="mt-3 font-semibold">{title}</h3><p className="mt-2 text-sm text-muted">{copy}</p></div></div>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
