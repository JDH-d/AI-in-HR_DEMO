import { BookOpen, ChevronDown } from "lucide-react";
import type { ChatMessage } from "../../api/types";

export function SourceEvidence({sources}: {sources: ChatMessage["sources"]}) {
  if (!sources?.length) return null;
  const documents = new Map<string, NonNullable<ChatMessage["sources"]>>();
  for (const source of sources) {
    const key = `${source.source}:${source.version}`;
    const entries = documents.get(key) ?? [];
    if (!entries.some(entry => entry.section === source.section && entry.excerpt === source.excerpt)) entries.push(source);
    documents.set(key, entries);
  }
  return <details className="group min-w-0 max-w-full open:w-full">
    <summary className="focus-ring flex min-h-11 w-fit list-none items-center gap-2 rounded-lg px-1 text-sm font-medium text-muted hover:text-cream">
      <BookOpen size={16} aria-hidden="true"/>Sources · {documents.size}<ChevronDown className="transition-transform group-open:rotate-180" size={15} aria-hidden="true"/>
    </summary>
    <div className="mb-1 space-y-2">{Array.from(documents.entries()).map(([key, entries]) => <details key={key} open={documents.size === 1 ? true : undefined} className="rounded-lg border border-line bg-panel p-3">
      <summary className="focus-ring min-h-11 rounded py-2 text-sm font-medium leading-6 [overflow-wrap:anywhere]">{entries[0].title} <span className="text-xs font-normal text-muted">· v{entries[0].version} · {entries.length} {entries.length === 1 ? "excerpt" : "excerpts"}</span></summary>
      {entries.map((source, index) => <div key={index} className="mt-3 border-t border-line pt-3">
        <p className="text-xs font-semibold text-muted">{source.section}</p>
        <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-lime/40 pl-3 text-sm leading-6">{source.excerpt.replace(/\*\*(.*?)\*\*/g, "$1").replace(/^#{1,6}\s+/gm, "")}</blockquote>
      </div>)}
    </details>)}</div>
  </details>;
}
