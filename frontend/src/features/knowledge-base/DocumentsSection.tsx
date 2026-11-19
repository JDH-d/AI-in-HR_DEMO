import { Download, FileText, FileUp, MoreHorizontal, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import type { DocumentItem } from "../../api/types";
import { Badge, Button, Card, Drawer, LoadingSkeleton, fieldClass, statusTone } from "../../components/ui";
import { useDocuments, useDocumentUpload } from "./useKnowledge";
import { KnowledgeEmptyState } from "./KnowledgeEmptyState";
import { KnowledgeToolbar } from "./KnowledgeToolbar";

export function DocumentsSection() {
  const { uploadOpen, setUploadOpen, deleteTarget, setDeleteTarget, downloadError, documents, list, stats, indexing, removing, download } = useDocuments();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState<DocumentItem | null>(null);
  const hasData = Boolean(documents.data);
  const needle = search.trim().toLowerCase();
  const visible = list.filter(item => (!needle || `${item.title} ${item.name} ${item.category} ${item.version}`.toLowerCase().includes(needle)) &&
    (status === "all" || (status === "processing" ? ["pending", "indexing"].includes(item.index_status) : item.index_status === status)));
  const clearFilters = () => { setSearch(""); setStatus("all"); };
  const activeDocument = selected ? list.find(item => item.id === selected.id) : undefined;
  const beginIndexing = (id: string) => { indexing.reset(); indexing.mutate(id); };

  return <div className="space-y-4">
    <Card padding="none">
      <h2 className="sr-only">Source library</h2>
      <KnowledgeToolbar summary={<><strong className="block text-cream">{hasData ? `${list.length} documents` : "Source library"}</strong><span aria-label="Document processing summary">{hasData ? stats.indexed : "—"} ready · {hasData ? stats.pending : "—"} processing · {hasData ? stats.errors : "—"} errors</span></>}
        actions={<><Button tone="ghost" className="knowledge-toolbar-refresh" aria-label="Refresh" disabled={documents.isFetching} onClick={() => void documents.refetch()}><RefreshCw size={16} aria-hidden="true"/></Button><Button onClick={() => setUploadOpen(true)}><Upload size={16} aria-hidden="true"/>Add document</Button></>}>
        <label className="knowledge-toolbar-search"><span className="sr-only">Search documents</span><Search size={17} aria-hidden="true"/><input className={`${fieldClass} pl-10`} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search library" maxLength={200}/></label>
        <label className="knowledge-toolbar-status"><span className="sr-only">Document status</span><select className={fieldClass} value={status} onChange={event => setStatus(event.target.value)}><option value="all">All statuses</option><option value="indexed">Ready</option><option value="processing">Processing</option><option value="error">Errors</option></select></label>
        {(needle || status !== "all") && <Button tone="ghost" onClick={clearFilters}>Clear filters</Button>}
      </KnowledgeToolbar>
      {downloadError && <p role="alert" className="m-4 rounded-lg bg-danger/10 p-3 text-sm text-danger">{downloadError} Try downloading the document again.</p>}
      {documents.isLoading && <LoadingSkeleton label="Loading source library…" className="p-4 sm:p-6"/>}
      {documents.isError && <div role="alert" className="m-4 space-y-3 rounded-lg border border-danger/25 bg-danger/5 p-4"><p className="font-semibold text-danger">Unable to load documents</p><p className="text-sm text-muted">{hasData ? "Showing the last loaded library. Its contents may be out of date." : "Check the connection and try again. The library has not been changed."}</p><Button tone="secondary" onClick={() => void documents.refetch()}>Retry documents</Button></div>}
      {documents.isSuccess && !list.length && <KnowledgeEmptyState title="No documents yet" copy="Add the first company policy or guide to give the assistant a reliable source."/>}
      {hasData && list.length > 0 && !visible.length && <KnowledgeEmptyState title="No matching documents" copy="Change the search or clear the filters to see the rest of the library."/>}
      {visible.length > 0 && <div className="knowledge-document-row knowledge-document-head border-b border-line bg-ink/50 px-4 py-2 text-xs font-medium text-muted" aria-hidden="true"><span>Document</span><span>Status</span><span>Updated</span><span className="text-right">Actions</span></div>}
      <div className="divide-y divide-line">
        {visible.map(document => <article key={document.id} className="min-w-0 px-3 py-3 sm:px-4">
          <div className="knowledge-document-row">
            <div className="knowledge-document-title min-w-0">
              <h3 className="text-sm font-semibold"><button onClick={() => setSelected(document)} className="focus-ring flex min-h-9 w-full items-center gap-2 rounded text-left hover:text-lime"><FileText size={18} className="shrink-0 text-muted" aria-hidden="true"/><span className="min-w-0 [overflow-wrap:anywhere]">{document.title}</span></button></h3>
              <p className="pl-6 text-xs text-muted [overflow-wrap:anywhere]">{document.category} · Version {document.version} · {formatBytes(document.size)}</p>
            </div>
            <div className="knowledge-document-meta"><Badge tone={statusTone(document.index_status)}>{documentStatus(document.index_status)}</Badge><span className="text-xs text-muted min-[1100px]:hidden">{formatDate(document.modified)}</span></div>
            <p className="knowledge-document-updated text-xs text-muted">{formatDate(document.modified)}</p>
            <div className="knowledge-document-actions">
              <Button tone="ghost" aria-label={`Download ${document.title}`} title="Download document" onClick={() => void download(document)}><Download size={16} aria-hidden="true"/></Button>
              <details className="relative" onKeyDown={event => {
                if (event.key !== "Escape") return;
                event.preventDefault();
                event.stopPropagation();
                event.currentTarget.open = false;
                event.currentTarget.querySelector("summary")?.focus();
              }} onBlur={event => {
                if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
              }}>
                <summary title="More actions" className="focus-ring flex min-h-9 cursor-pointer items-center justify-center rounded px-2 text-sm text-muted hover:bg-raised"><MoreHorizontal size={19} aria-hidden="true"/><span className="sr-only">More actions<span> for {document.title}</span></span></summary>
                <div className="absolute right-0 z-30 mt-1 flex w-52 max-w-[calc(100vw-3rem)] flex-col gap-1 rounded-lg border border-line bg-panel p-2 shadow-lg" onClick={event => { const element = event.target as HTMLElement; if (element.closest('button')) { const menu = event.currentTarget.closest('details'); menu?.removeAttribute('open'); menu?.querySelector('summary')?.focus(); } }}>
                  <Button tone="ghost" className="justify-start" onClick={() => setSelected(document)}>Document details<span className="sr-only">: {document.title}</span></Button>
                  <Button tone="ghost" className="justify-start" onClick={() => beginIndexing(document.id)} disabled={indexing.isPending || document.index_status === "indexing"}>{indexing.isPending && indexing.variables === document.id ? "Processing…" : document.index_status === "indexed" ? "Re-index" : "Index document"}<span className="sr-only">: {document.title}</span></Button>
                  <div className="my-1 border-t border-line"/>
                  <Button tone="danger" className="justify-start" onClick={() => { removing.reset(); setDeleteTarget(document); }}><Trash2 size={16} aria-hidden="true"/>Remove document<span className="sr-only">: {document.title}</span></Button>
                </div>
              </details>
            </div>
          </div>
          {document.index_error && <p role="status" className="mt-2 rounded bg-danger/10 p-2 text-sm leading-5 text-danger [overflow-wrap:anywhere]">{document.index_error}</p>}
          {indexing.isPending && indexing.variables === document.id && <p role="status" className="mt-2 text-sm text-muted">Processing this document. It will be available after indexing finishes.</p>}
        </article>)}
      </div>
      {hasData && list.length > 0 && <p role="status" className="border-t border-line px-4 py-2 text-xs text-muted">{visible.length} of {list.length} documents</p>}
    </Card>
    {indexing.isError && <p role="alert" className="rounded-lg bg-danger/10 p-3 text-sm text-danger">{indexing.error instanceof Error ? indexing.error.message : "Indexing failed. Check the document and try again."}</p>}
    {indexing.isSuccess && <p role="status" className="success-feedback text-sm text-muted">Document processing completed.</p>}
    <Drawer open={Boolean(selected)} onOpenChange={open => !open && setSelected(null)} title="Document details" description="Source information and processing status." size="medium" footer={activeDocument && <Button tone="secondary" onClick={() => void download(activeDocument)}><Download size={16} aria-hidden="true"/>Download document</Button>}>
      {activeDocument ? <div className="space-y-4"><div><h3 className="font-semibold [overflow-wrap:anywhere]">{activeDocument.title}</h3><p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">{activeDocument.name}</p></div><Badge tone={statusTone(activeDocument.index_status)}>{documentStatus(activeDocument.index_status)}</Badge><dl className="grid grid-cols-2 gap-4 text-sm">{[["Category",activeDocument.category],["Version",activeDocument.version],["File size",formatBytes(activeDocument.size)],["Updated",formatDate(activeDocument.modified)],["Searchable passages",activeDocument.chunk_count],["Last indexed",activeDocument.indexed_at ? new Date(activeDocument.indexed_at).toLocaleString() : "Not indexed yet"]].map(([label,value]) => <div key={String(label)}><dt className="text-muted">{label}</dt><dd className="mt-1 font-medium [overflow-wrap:anywhere]">{value}</dd></div>)}</dl>{activeDocument.index_error && <p role="alert" className="text-sm text-danger">{activeDocument.index_error}</p>}{downloadError && <p role="alert" className="text-sm text-danger">{downloadError} Try downloading again.</p>}</div> : <p role="status" className="text-sm text-muted">This document is no longer in the library. Close this panel and refresh the list.</p>}
    </Drawer>
    <UploadDocumentDialog open={uploadOpen} onOpenChange={setUploadOpen}/>
    <Drawer open={Boolean(deleteTarget)} onOpenChange={open => !open && !removing.isPending && setDeleteTarget(null)} title="Remove document?" description="Future answers will stop using this source. Existing chat messages will remain." placement="center" size="small" footer={<><Button tone="secondary" disabled={removing.isPending} onClick={() => setDeleteTarget(null)}>Keep document</Button><Button tone="danger" onClick={() => deleteTarget && removing.mutate(deleteTarget.id)} disabled={removing.isPending}><Trash2 size={16} aria-hidden="true"/>{removing.isPending ? "Removing…" : "Remove and rebuild"}</Button></>}>
      {deleteTarget && <div className="space-y-4"><div className="min-w-0 rounded-lg bg-ink p-3"><p className="font-semibold [overflow-wrap:anywhere]">{deleteTarget.title}</p><p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">{deleteTarget.name}</p></div><p className="text-sm leading-6">This permanently removes the document and rebuilds the knowledge index.</p>{removing.isError && <p role="alert" className="text-sm text-danger">{removing.error instanceof Error ? removing.error.message : "Removal failed. Try again."}</p>}</div>}
    </Drawer>
  </div>;
}

function UploadDocumentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { file, setFile, autoIndex, aiSettings, upload } = useDocumentUpload(onOpenChange);
  const close = (next: boolean) => {
    if (upload.isPending) return;
    if (!next) { setFile(null); upload.reset(); }
    onOpenChange(next);
  };
  return <Drawer open={open} onOpenChange={close} title="Add a knowledge document" description="Choose a company policy or guide." placement="center" size="medium" footer={<><Button tone="secondary" disabled={upload.isPending} onClick={() => close(false)}>Cancel</Button><Button onClick={() => upload.mutate()} disabled={!file || upload.isPending}><Upload size={16} aria-hidden="true"/>{upload.isPending ? "Uploading…" : "Add document"}</Button></>}>
    <div className="space-y-4">
      <label className="grid min-h-32 cursor-pointer place-items-center rounded-lg border border-dashed border-line bg-ink/40 p-4 text-center transition focus-within:ring-2 focus-within:ring-lime hover:bg-raised">
        <input className="sr-only" aria-label="Choose a document" type="file" accept=".md,.txt,.pdf,.docx" disabled={upload.isPending} onChange={event => setFile(event.target.files?.[0] ?? null)}/>
        <span><FileUp size={24} className="mx-auto text-muted" aria-hidden="true"/><span className="mt-2 block text-sm font-semibold">Choose a document</span><span className="mt-1 block text-xs leading-5 text-muted">Markdown, TXT, PDF or DOCX · up to 10 MB</span></span>
      </label>
      {file && <div className="min-w-0 rounded-lg bg-ink p-3"><p className="text-sm font-semibold [overflow-wrap:anywhere]">{file.name}</p><p className="mt-1 text-xs text-muted">{formatBytes(file.size)} · {upload.isPending ? "Uploading and preparing document…" : "Ready to upload"}</p></div>}
      <p className="text-sm leading-6 text-muted">{aiSettings.isLoading || aiSettings.isError ? "Processing will follow the saved AI settings on the server." : autoIndex ? "The assistant will be able to use this document after automatic indexing finishes." : "This document will be saved. Use Index document when it is ready for the assistant."}</p>
      {upload.isPending && <p role="status" className="text-sm text-muted">Keep this window open until the upload finishes.</p>}
      {upload.isError && <p role="alert" className="rounded-lg bg-danger/10 p-3 text-sm text-danger">{upload.error instanceof Error ? upload.error.message : "Upload failed. Choose a supported file and try again."}</p>}
    </div>
  </Drawer>;
}
function documentStatus(status: string): string { return status === "indexed" ? "Ready" : status === "pending" ? "Waiting to process" : status === "indexing" ? "Processing" : status === "error" ? "Error" : status.replaceAll("_", " "); }
function formatDate(value: string): string { return new Date(value).toLocaleDateString(); }
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
