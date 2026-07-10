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
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { api, downloadFile } from "../../api/client";
import type { DocumentItem, FeedbackItem, Metrics } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Badge, Button, Card, Drawer, Hint, fieldClass, statusTone } from "../../components/ui";

type Section = "overview" | "documents" | "unanswered" | "feedback" | "settings";

const navigation: [Section, string, ReactNode][] = [
  ["overview", "Overview", <BarChart3 />],
  ["documents", "Documents", <BookOpen />],
  ["unanswered", "Unanswered", <MessageSquareWarning />],
  ["feedback", "Feedback", <ThumbsUp />],
  ["settings", "System settings", <Settings2 />],
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
      {section === "unanswered" && <Unanswered />}
      {section === "feedback" && <Feedback metrics={metrics.data?.metrics} />}
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
  const [indexNow, setIndexNow] = useState(true);
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a document before uploading.");
      const form = new FormData();
      form.append("file", file);
      const result = await api<{ document: DocumentItem }>("/api/v1/documents", token, { method: "POST", body: form });
      if (indexNow) await api(`/api/v1/documents/${result.document.id}/index`, token, { method: "POST" });
      return result;
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
      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-4"><input type="checkbox" checked={indexNow} onChange={event => setIndexNow(event.target.checked)} className="mt-1 accent-[#c9f45b]" /><span><strong className="block text-sm">Index immediately</strong><span className="mt-1 block text-xs leading-5 text-muted">Recommended. The document becomes available to the assistant as soon as processing finishes.</span></span></label>
      {upload.isError && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{upload.error instanceof Error ? upload.error.message : "Upload failed"}</p>}
      <div className="flex justify-end gap-3"><Button tone="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={() => upload.mutate()} disabled={!file || upload.isPending}><Upload size={16} />{upload.isPending ? (indexNow ? "Uploading and indexing…" : "Uploading…") : "Add document"}</Button></div>
    </div>
  </Drawer>;
}

function Feedback({ metrics }: { metrics?: Metrics }) {
  const { token } = useAuth();
  const [mode, setMode] = useState<"negative" | "positive">("negative");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<FeedbackItem | null>(null);
  const feedback = useQuery({
    queryKey: ["admin-feedback"],
    queryFn: () => api<{ feedback: FeedbackItem[] }>("/api/v1/admin/feedback?sentiment=all&limit=500", token),
  });
  const items = feedback.data?.feedback ?? [];
  const counts = {
    positive: items.filter(item => item.sentiment === "positive").length,
    negative: items.filter(item => item.sentiment === "negative").length,
  };
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return items.filter(item => item.sentiment === mode && (!needle || `${item.question} ${item.answer} ${item.comment}`.toLowerCase().includes(needle)));
  }, [items, mode, search]);

  return <div className="space-y-5">
    <div className="grid gap-3 md:grid-cols-3">
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Helpful rate</p><strong className="mt-4 block text-4xl text-lime">{metrics?.positive_feedback_rate ?? 0}%</strong><p className="mt-2 text-xs text-muted">Share of all ratings marked helpful</p></Card>
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Needs review</p><strong className="mt-4 block text-4xl text-danger">{counts.negative}</strong><p className="mt-2 text-xs text-muted">Answers that may need a content fix</p></Card>
      <Card className="p-5"><p className="text-[10px] uppercase tracking-wider text-muted">Helpful answers</p><strong className="mt-4 block text-4xl">{counts.positive}</strong><p className="mt-2 text-xs text-muted">Examples worth learning from</p></Card>
    </div>
    <Card className="overflow-hidden p-0">
      <div className="border-b border-line p-5">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div><h2 className="font-semibold">Response review</h2><p className="mt-1 text-xs text-muted">Inspect the exact question and AI answer. Employee identity is never shown here.</p></div>
          <Button tone="secondary" onClick={() => feedback.refetch()}><RefreshCw size={15} />Refresh</Button>
        </div>
        <div className="mt-5 flex flex-col gap-3 sm:flex-row">
          <div className="grid grid-cols-2 rounded-xl border border-line bg-ink p-1">
            <button onClick={() => setMode("negative")} className={`focus-ring rounded-lg px-4 py-2 text-xs font-semibold ${mode === "negative" ? "bg-danger/15 text-danger" : "text-muted hover:text-cream"}`}><ThumbsDown className="mr-2 inline" size={14} />Needs review · {counts.negative}</button>
            <button onClick={() => setMode("positive")} className={`focus-ring rounded-lg px-4 py-2 text-xs font-semibold ${mode === "positive" ? "bg-lime-soft text-lime" : "text-muted hover:text-cream"}`}><ThumbsUp className="mr-2 inline" size={14} />Helpful · {counts.positive}</button>
          </div>
          <label className="relative flex-1"><Search className="absolute left-3 top-3 text-muted" size={17} /><input className={`${fieldClass} pl-10`} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search questions, answers, or notes" /></label>
        </div>
      </div>
      {feedback.isLoading && <div className="grid min-h-56 place-items-center text-sm text-muted">Loading feedback signals…</div>}
      {feedback.isError && <div className="grid min-h-56 place-items-center text-sm text-danger">Unable to load feedback.</div>}
      {!feedback.isLoading && !visible.length && <Empty title={mode === "negative" ? "No answers need review" : "No helpful examples yet"} copy={search ? "Try a different search." : "New response ratings will appear here automatically."} />}
      <div className="divide-y divide-line">
        {visible.map(item => <button key={item.id} onClick={() => setSelected(item)} className="focus-ring grid w-full gap-4 p-5 text-left transition hover:bg-raised/60 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_140px]">
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-coral">Employee question</p><p className="mt-2 line-clamp-3 text-sm font-semibold leading-6">{item.question || "Question was not captured"}</p></div>
          <div><p className="text-[10px] font-bold uppercase tracking-wider text-muted">AI answer</p><p className="mt-2 line-clamp-3 text-sm leading-6 text-muted">{item.answer || "Answer was not captured for this older feedback signal."}</p>{item.comment && <p className="mt-3 line-clamp-2 rounded-lg bg-danger/8 px-3 py-2 text-xs text-cream">“{item.comment}”</p>}</div>
          <div className="flex items-start justify-between gap-3 lg:block lg:text-right"><Badge tone={item.sentiment === "positive" ? "success" : "danger"}>{item.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><p className="mt-2 text-[10px] text-muted">{new Date(item.created_at).toLocaleString()}</p><p className="mt-2 text-[10px] uppercase tracking-wider text-muted">Anonymous</p></div>
        </button>)}
      </div>
    </Card>
    <Drawer open={Boolean(selected)} onOpenChange={open => !open && setSelected(null)} title="Response feedback" description="An anonymized view of the exact exchange the employee rated." placement="center">
      {selected && <div className="space-y-5">
        <div className="flex items-center justify-between"><Badge tone={selected.sentiment === "positive" ? "success" : "danger"}>{selected.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><span className="flex items-center gap-2 text-xs text-muted"><ShieldCheck size={15} />Anonymous</span></div>
        <ConversationBlock label="Employee question" text={selected.question || "Question was not captured."} accent="coral" />
        <ConversationBlock label="PeopleFlow answer" text={selected.answer || "Answer was not captured for this older feedback signal."} accent="lime" />
        {selected.comment && <section className="rounded-2xl border border-danger/25 bg-danger/10 p-5"><p className="text-[10px] font-bold uppercase tracking-wider text-danger">Employee note</p><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{selected.comment}</p></section>}
        <p className="text-right text-xs text-muted">Received {new Date(selected.created_at).toLocaleString()}</p>
      </div>}
    </Drawer>
  </div>;
}

function ConversationBlock({ label, text, accent }: { label: string; text: string; accent: "coral" | "lime" }) {
  return <section className="rounded-2xl border border-line bg-ink/50 p-5"><p className={`text-[10px] font-bold uppercase tracking-wider ${accent === "coral" ? "text-coral" : "text-lime"}`}>{label}</p><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-cream">{text}</p></section>;
}

function Unanswered() {
  const { token } = useAuth();
  const questions = useQuery({ queryKey: ["unanswered"], queryFn: () => api<{ questions: { timestamp: string; question: string; assistant: string }[] }>("/api/v1/admin/unanswered", token) });
  return <div className="space-y-3">
    {questions.data?.questions.map((item, index) => <Card key={`${item.timestamp}-${index}`}><div className="flex gap-3"><AlertTriangle className="mt-1 text-coral" size={18} /><div><strong className="text-sm">{item.question}</strong><p className="mt-2 text-xs leading-5 text-muted">{item.assistant}</p><p className="mt-3 text-[10px] uppercase tracking-wider text-muted">{new Date(item.timestamp).toLocaleString()}</p></div></div></Card>)}
    {!questions.data?.questions.length && <Empty title="No unanswered questions" copy="New knowledge gaps will appear here automatically." />}
  </div>;
}

function Settings() {
  const { token } = useAuth();
  const [prompt, setPrompt] = useState("");
  const load = useQuery({ queryKey: ["system-prompt"], queryFn: () => api<{ system_prompt: string }>("/api/v1/admin/system-prompt", token) });
  if (load.data && !prompt) setPrompt(load.data.system_prompt);
  const save = useMutation({ mutationFn: () => api("/api/v1/admin/system-prompt", token, { method: "PUT", body: JSON.stringify({ system_prompt: prompt }) }) });
  return <Card className="max-w-3xl"><h2 className="font-semibold">Assistant behavior</h2><p className="mt-2 text-sm leading-6 text-muted">Advanced setting. Document quality and unanswered questions should be reviewed before changing this prompt.</p><textarea className={`${fieldClass} mt-6 min-h-56 font-mono text-xs leading-6`} value={prompt} onChange={event => setPrompt(event.target.value)} /><div className="mt-4 flex justify-end"><Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isSuccess ? "Saved" : "Save settings"}</Button></div></Card>;
}

function Empty({ title, copy }: { title: string; copy: string }) {
  return <div className="grid min-h-56 place-items-center p-6 text-center"><div><CheckCircle2 className="mx-auto text-lime" /><h3 className="mt-3 font-semibold">{title}</h3><p className="mt-2 text-sm text-muted">{copy}</p></div></div>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
