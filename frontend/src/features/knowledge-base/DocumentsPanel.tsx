import {
  ArrowsClockwise,
  DownloadSimple,
  FileArrowUp,
  FileText,
  Trash,
  UploadSimple,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, downloadFile } from "../../api/client";
import type { AISettingsResponse, DocumentItem } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Card, Drawer, Hint, statusTone } from "../../components/ui";

export function DocumentsPanel() {
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
    indexed: list.filter((item) => item.index_status === "indexed").length,
    pending: list.filter((item) => ["pending", "indexing"].includes(item.index_status)).length,
    errors: list.filter((item) => item.index_status === "error").length,
  };
  const lexicalFallback = list.some(
    (item) => item.index_status === "indexed" && item.index_mode === "lexical",
  );
  const indexing = useMutation({
    mutationFn: () => api("/api/v1/documents/index", token, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });
  const removing = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}`, token, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });

  const download = async (document: DocumentItem) => {
    setDownloadError("");
    try {
      await downloadFile(
        `/api/v1/documents/${document.id}/download`,
        token,
        document.name.split("/").pop() ?? document.name,
      );
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Unable to download the document");
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <DocumentMetric
          label="Indexed"
          value={documents.data ? stats.indexed : "—"}
          copy="Ready for grounded answers"
          tone="success"
        />
        <DocumentMetric
          label="Pending"
          value={documents.data ? stats.pending : "—"}
          copy="Waiting for indexing"
          tone="warning"
        />
        <DocumentMetric
          label="Errors"
          value={documents.data ? stats.errors : "—"}
          copy="Need administrator attention"
          tone="danger"
        />
      </div>

      {lexicalFallback && (
        <div
          role="status"
          className="flex items-start gap-3 rounded-lg border border-warning/20 bg-warning/5 p-4 text-sm"
        >
          <Warning className="mt-0.5 shrink-0 text-warning" size={18} />
          <div>
            <p className="font-semibold text-cream">Lexical search is active</p>
            <p className="mt-1 text-sm leading-6 text-muted">
              The index remains usable, and semantic embeddings will retry automatically when the
              OpenAI connection is available.
            </p>
          </div>
        </div>
      )}

      <Card className="overflow-hidden p-0">
        <div className="flex flex-col gap-4 border-b border-line px-5 py-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h2 className="text-sm font-semibold">Source library</h2>
            <p className="mt-1 text-sm text-muted">
              {documents.data
                ? `${list.length} company documents`
                : "Company policies and handbooks"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              tone="ghost"
              onClick={() => documents.refetch()}
              disabled={documents.isFetching}
            >
              <ArrowsClockwise size={18} className={documents.isFetching ? "animate-spin" : ""} />
              Refresh
            </Button>
            <Button
              tone="secondary"
              onClick={() => indexing.mutate()}
              disabled={indexing.isPending || documents.isLoading || !list.length}
            >
              <ArrowsClockwise className={indexing.isPending ? "animate-spin" : ""} size={18} />
              {indexing.isPending ? "Rebuilding…" : "Rebuild index"}
            </Button>
            <Button onClick={() => setUploadOpen(true)}>
              <UploadSimple size={18} />
              Add document
            </Button>
          </div>
        </div>

        {downloadError && (
          <p className="m-4 rounded-lg bg-danger/10 p-3 text-sm text-danger">{downloadError}</p>
        )}
        {indexing.isError && (
          <p className="m-4 rounded-lg bg-danger/10 p-3 text-sm text-danger">
            {indexing.error instanceof Error ? indexing.error.message : "Indexing failed"}
          </p>
        )}
        {documents.isLoading && (
          <div className="grid min-h-48 place-items-center text-sm text-muted">
            Loading source library…
          </div>
        )}
        {documents.isError && (
          <div className="grid min-h-48 place-items-center p-6 text-center">
            <div>
              <p className="text-sm font-medium">Unable to load documents</p>
              <Button tone="secondary" className="mt-3" onClick={() => documents.refetch()}>
                Try again
              </Button>
            </div>
          </div>
        )}
        {!documents.isLoading && !documents.isError && list.length === 0 && (
          <Empty
            title="No documents yet"
            copy="Upload the first policy or handbook to create the knowledge base."
            onAdd={() => setUploadOpen(true)}
          />
        )}
        <div className="divide-y divide-line">
          {list.map((document) => (
            <div
              key={document.id}
              className="grid gap-4 px-5 py-4 transition hover:bg-ink lg:grid-cols-[minmax(0,1.45fr)_minmax(130px,.7fr)_65px_150px_auto] lg:items-center"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <FileText size={20} className="shrink-0 text-muted" />
                  <strong className="truncate text-sm font-medium">{document.title}</strong>
                </div>
                <p className="mt-1 truncate text-xs text-muted">
                  {document.name} · {formatBytes(document.size)}
                </p>
                {document.index_error && (
                  <p className="mt-2 text-xs leading-5 text-danger">{document.index_error}</p>
                )}
              </div>
              <div>
                <span className="text-xs text-muted">Category</span>
                <p className="mt-1 text-sm">
                  {document.category} · v{document.version}
                </p>
              </div>
              <div>
                <span className="text-xs text-muted">Chunks</span>
                <p className="mt-1 text-sm font-semibold">{document.chunk_count}</p>
              </div>
              <div>
                <Badge tone={statusTone(document.index_status)}>{document.index_status}</Badge>
                <p className="mt-2 text-xs text-muted">
                  {document.indexed_at
                    ? new Date(document.indexed_at).toLocaleString()
                    : "Never indexed"}
                </p>
              </div>
              <div className="flex items-center justify-end gap-1">
                <Hint label="Download document">
                  <Button
                    tone="ghost"
                    aria-label={`Download ${document.title}`}
                    className="h-9 w-9"
                    style={{ padding: 0 }}
                    onClick={() => void download(document)}
                  >
                    <DownloadSimple size={18} />
                  </Button>
                </Hint>
                <Hint label="Delete document">
                  <Button
                    tone="ghost"
                    aria-label={`Delete ${document.title}`}
                    className="h-9 w-9 text-danger"
                    style={{ padding: 0 }}
                    onClick={() => setDeleteTarget(document)}
                  >
                    <Trash size={18} />
                  </Button>
                </Hint>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <UploadDocumentDialog open={uploadOpen} onOpenChange={setUploadOpen} />
      <Drawer
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Remove document?"
        description="This action also rebuilds the knowledge index so the assistant stops using this source."
        placement="center"
      >
        {deleteTarget && (
          <div className="space-y-5">
            <Card className="bg-ink">
              <p className="text-xs font-medium text-muted">Document</p>
              <p className="mt-2 font-semibold">{deleteTarget.title}</p>
              <p className="mt-1 text-xs text-muted">{deleteTarget.name}</p>
            </Card>
            <div className="rounded-lg border border-danger/25 bg-danger/10 p-4 text-sm leading-6 text-cream">
              Deleting an outdated source is permanent. Future answers will no longer retrieve
              evidence from it.
            </div>
            {removing.isError && (
              <p className="text-sm text-danger">
                {removing.error instanceof Error ? removing.error.message : "Deletion failed"}
              </p>
            )}
            <div className="flex justify-end gap-3">
              <Button tone="secondary" onClick={() => setDeleteTarget(null)}>
                Keep document
              </Button>
              <Button
                tone="danger"
                onClick={() => removing.mutate(deleteTarget.id)}
                disabled={removing.isPending}
              >
                <Trash size={18} />
                {removing.isPending ? "Removing…" : "Remove and rebuild"}
              </Button>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

function DocumentMetric({
  label,
  value,
  copy,
  tone,
}: {
  label: string;
  value: number | string;
  copy: string;
  tone: "success" | "warning" | "danger";
}) {
  const color =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : "text-danger";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{label}</p>
        <strong className={`text-xl font-semibold tabular-nums ${color}`}>{value}</strong>
      </div>
      <p className="mt-1 text-sm text-muted">{copy}</p>
    </Card>
  );
}

function UploadDocumentDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const aiSettings = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token),
  });
  const autoIndex = aiSettings.data?.settings.auto_index_uploads;
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a document before uploading.");
      const form = new FormData();
      form.append("file", file);
      return api<{ document: DocumentItem }>("/api/v1/documents", token, {
        method: "POST",
        body: form,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
      setFile(null);
      onOpenChange(false);
    },
  });

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Add a knowledge document"
      description="Supported files become private sources for grounded assistant answers."
      placement="center"
    >
      <div className="space-y-5">
        <label className="grid min-h-40 cursor-pointer place-items-center rounded-lg border border-dashed border-line bg-ink p-5 text-center transition focus-within:ring-2 focus-within:ring-accent/40 hover:border-accent/50 hover:bg-accent-soft/30">
          <input
            className="sr-only"
            type="file"
            accept=".md,.txt,.pdf,.docx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <div>
            <div className="mx-auto grid h-10 w-10 place-items-center rounded-lg bg-accent-soft text-accent">
              <FileArrowUp size={20} />
            </div>
            <p className="mt-4 text-sm font-semibold">Choose a document</p>
            <p className="mt-2 text-xs text-muted">Markdown, TXT, PDF, or DOCX · maximum 10 MB</p>
          </div>
        </label>
        {file && (
          <Card className="flex items-center justify-between gap-4 bg-ink p-4">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{file.name}</p>
              <p className="mt-1 text-xs text-muted">{formatBytes(file.size)}</p>
            </div>
            <Badge tone="warning">Ready to upload</Badge>
          </Card>
        )}
        <div className="flex items-start justify-between gap-4 rounded-lg border border-line p-4">
          <span>
            <strong className="block text-sm">Automatic indexing</strong>
            <span className="mt-1 block text-sm leading-6 text-muted">
              Controlled globally from AI settings.{" "}
              {aiSettings.isLoading
                ? "Checking the saved setting…"
                : aiSettings.isError
                  ? "The saved setting is unavailable; the server will apply it when you upload."
                  : autoIndex
                    ? "This upload will be indexed immediately."
                    : "This upload will wait for a manual rebuild."}
            </span>
          </span>
          <Badge tone={autoIndex === true ? "success" : "neutral"}>
            {aiSettings.isLoading
              ? "Checking"
              : aiSettings.isError
                ? "Unavailable"
                : autoIndex
                  ? "On"
                  : "Off"}
          </Badge>
        </div>
        {upload.isError && (
          <p className="rounded-lg bg-danger/10 p-3 text-sm text-danger">
            {upload.error instanceof Error ? upload.error.message : "Upload failed"}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <Button tone="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => upload.mutate()} disabled={!file || upload.isPending}>
            <UploadSimple size={18} />
            {upload.isPending
              ? autoIndex === true
                ? "Uploading and indexing…"
                : "Uploading…"
              : "Add document"}
          </Button>
        </div>
      </div>
    </Drawer>
  );
}

function Empty({ title, copy, onAdd }: { title: string; copy: string; onAdd: () => void }) {
  return (
    <div className="grid min-h-56 place-items-center p-6 text-center">
      <div>
        <FileText className="mx-auto text-muted" size={24} />
        <h3 className="mt-3 font-semibold">{title}</h3>
        <p className="mt-2 text-sm text-muted">{copy}</p>
        <Button className="mt-4" onClick={onAdd}>
          <UploadSimple size={18} />
          Add document
        </Button>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
