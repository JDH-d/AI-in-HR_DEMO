import type { ReactNode } from "react";

/** Shared command and filter placement for the administrator's working lists. */
export function KnowledgeToolbar({ summary, actions, children }: { summary: ReactNode; actions: ReactNode; children: ReactNode }) {
  return <div className="knowledge-toolbar">
    <div className="knowledge-toolbar-commands"><div className="knowledge-toolbar-summary">{summary}</div><div className="knowledge-toolbar-actions">{actions}</div></div>
    <div className="knowledge-toolbar-filters">{children}</div>
  </div>;
}
