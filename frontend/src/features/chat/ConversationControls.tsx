import { useEffect, useRef, useState } from "react";
import { Ellipsis, History as HistoryIcon, MessageSquarePlus, Pencil, Search, Trash2, X } from "lucide-react";
import { Button, Drawer, LoadingSkeleton, fieldClass } from "../../components/ui";
import type { useConversations } from "./useConversations";
import "./conversation-controls.css";

type History = ReturnType<typeof useConversations>;

export function ConversationSearch({history, onShowHistory}: {history: History; onShowHistory: () => void}) {
  const input = useRef<HTMLInputElement>(null);
  return <div className="flex min-w-0 items-center gap-1">
    <div className="relative min-w-0 flex-1">
      <label className="block">
        <span className="sr-only">Search history</span>
        <input ref={input} type="search" className={`conversation-search-input ${fieldClass} pl-9 ${history.search ? "pr-11" : "pr-3"}`} placeholder="Search chats" value={history.search}
          maxLength={200} onChange={event => history.setSearch(event.target.value)}/>
      </label>
      <Search size={16} className="pointer-events-none absolute left-3 top-3.5 text-muted" aria-hidden="true"/>
      {history.search && <button type="button" aria-label="Clear history search" onClick={() => { history.setSearch(""); input.current?.focus(); }}
        className="focus-ring absolute right-0 top-0 grid h-11 w-11 touch-manipulation place-items-center rounded-lg text-muted transition-colors hover:bg-raised hover:text-cream"><X size={16} aria-hidden="true"/></button>}
    </div>
    <Button tone="secondary" onClick={onShowHistory} className="shrink-0 px-3 lg:hidden" aria-label="Show conversation history">
      <HistoryIcon size={16} aria-hidden="true"/><span>History</span>
    </Button>
  </div>;
}

export function ConversationList({history}: {history: History}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const loading = Boolean(history.searchPending || history.list.isLoading);
  // During debounce the query still contains the previous search's results.
  const rows = history.searchPending ? [] : history.list.data?.pages.flatMap(page => page.conversations) ?? [];
  return <section aria-label="Your conversations" aria-busy={loading} className="mb-6">
    <Button tone="secondary" className="mb-3 w-full" onClick={() => void history.newConversation()} disabled={history.busy}>
      <MessageSquarePlus size={16}/>New conversation
    </Button>
    <h2 ref={heading} tabIndex={-1} className="mb-2 px-2 text-xs font-semibold text-muted outline-none">{history.search ? "Search results" : "Recent conversations"}</h2>
    {history.search && <p className="mb-2 px-2 text-xs text-muted [overflow-wrap:anywhere]">Matching “{history.search}”</p>}
    {loading && <LoadingSkeleton rows={2} label={history.search ? "Searching conversations…" : "Loading conversations…"}/>}
    {!history.searchPending && history.list.isError && <div role="alert" className="text-xs text-danger">Unable to load history.
      <Button tone="ghost" onClick={() => void history.list.refetch()}>Retry history</Button></div>}
    {!loading && history.list.isSuccess && rows.length === 0 && <div className="py-3">
      <p role="status" className="text-xs leading-5 text-muted">{history.search ? "No conversations match your search. Change your query or clear the search to see all conversations." : "No conversations yet. Send a message to start one."}</p>
      {history.search && <Button tone="secondary" className="mt-3" onClick={() => { history.setSearch(""); heading.current?.focus(); }}>Clear search</Button>}
    </div>}
    <div className="space-y-1">{rows.map(conversation => <button key={conversation.id}
      className={`focus-ring min-w-0 w-full touch-manipulation rounded-md border px-2 py-2 text-left transition-colors disabled:opacity-50 ${history.id === conversation.id ? "border-lime/40 bg-lime-soft" : "border-transparent hover:bg-raised"}`}
      aria-current={history.id === conversation.id ? "page" : undefined} disabled={history.busy}
      onClick={() => history.select(conversation.id)}>
      <span title={conversation.title} className="line-clamp-2 text-sm font-medium leading-5 [overflow-wrap:anywhere]">{conversation.title}</span>
      <time dateTime={conversation.updated_at} title={new Date(conversation.updated_at).toLocaleString()} className="mt-1 block text-xs text-muted">{new Date(conversation.updated_at).toLocaleDateString()}</time>
    </button>)}</div>
    {!loading && history.list.hasNextPage && <Button tone="ghost" disabled={history.list.isFetchingNextPage}
      onClick={() => void history.list.fetchNextPage()}>Load more conversations</Button>}
  </section>;
}

export function ConversationActions({history}: {history: History}) {
  const [dialog, setDialog] = useState<"menu" | "rename" | "delete" | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const titleField = useRef<HTMLInputElement>(null);
  const dialogActions = useRef<HTMLDivElement>(null);
  const conversation = history.detail.data?.conversation;
  useEffect(() => {
    if (dialog === "rename") titleField.current?.focus();
    if (dialog === "delete") dialogActions.current?.querySelector("button")?.focus();
  }, [dialog]);
  if (!conversation) return null;
  const open = (mode: "rename" | "delete") => { setDialog(mode); setTitle(conversation.title); setError(""); };
  const confirm = async () => {
    setSaving(true); setError("");
    try { if (dialog === "rename") await history.rename(title.trim()); else await history.remove(); setDialog(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to save changes."); }
    finally { setSaving(false); }
  };
  return <>
    <div className="conversation-heading flex min-w-0 flex-1 items-center gap-1">
      <h1 title={conversation.title} className="min-w-0 flex-1 line-clamp-2 text-sm font-semibold [overflow-wrap:anywhere] sm:text-base">{conversation.title}</h1>
      <Button tone="ghost" className="h-11 w-11 shrink-0 p-0" aria-label="Conversation actions" aria-haspopup="dialog" aria-expanded={Boolean(dialog)} disabled={history.pending} onClick={() => { setError(""); setDialog("menu"); }}><Ellipsis size={20} aria-hidden="true"/></Button>
    </div>
    <Drawer open={Boolean(dialog)} onOpenChange={value => { if (!value && !saving) setDialog(null); }}
      title={dialog === "menu" ? "Conversation actions" : dialog === "rename" ? "Rename conversation" : "Delete conversation?"}
      description={dialog === "menu" ? conversation.title : dialog === "rename" ? "Choose a name that helps you find this conversation." : "This permanently deletes this conversation and its messages. Unsent text in this chat is also discarded. Existing requests remain unchanged."}
      placement="center" size="small" footer={dialog !== "menu" && <div ref={dialogActions} className="form-actions">
        <Button tone="secondary" disabled={saving} onClick={() => setDialog(null)}>Cancel</Button>
        <Button tone={dialog === "delete" ? "danger" : "primary"} disabled={saving || (dialog === "rename" && !title.trim())} onClick={() => void confirm()}>
          {saving ? "Saving…" : dialog === "rename" ? "Save name" : "Delete permanently"}
        </Button>
      </div>}>
      {dialog === "menu" && <div className="space-y-2">
        <Button tone="ghost" className="w-full justify-start" onClick={() => open("rename")}><Pencil size={16} aria-hidden="true"/>Rename conversation</Button>
        <div className="border-t border-line pt-2"><Button tone="danger" className="w-full justify-start" onClick={() => open("delete")}><Trash2 size={16} aria-hidden="true"/>Delete conversation</Button></div>
      </div>}
      {dialog === "rename" && <label className="block text-sm">Conversation title
        <input ref={titleField} className={`${fieldClass} mt-2`} disabled={saving} value={title} maxLength={120} onChange={event => setTitle(event.target.value)} onKeyDown={event => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing && title.trim() && !saving) { event.preventDefault(); void confirm(); }
        }}/></label>}
      {dialog === "delete" && <p className="text-sm [overflow-wrap:anywhere]">{conversation.title}</p>}
      {error && <p role="alert" className="mt-4 text-sm text-danger">{error}</p>}
    </Drawer>
  </>;
}
