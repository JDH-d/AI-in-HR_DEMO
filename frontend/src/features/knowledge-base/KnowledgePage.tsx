import { RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router";
import { Shell } from "../../components/Shell";
import { Button, PageHeader } from "../../components/ui";
import { useKnowledgeMetrics } from "./useKnowledge";
import type { KnowledgeSection } from "./types";
import { OverviewSection } from "./OverviewSection";
import { DocumentsSection } from "./DocumentsSection";
import { QualitySection } from "./QualitySection";
import { SettingsSection } from "./SettingsSection";
import { IntegrationsSection } from "../integrations/IntegrationsSection";
import "./knowledge.css";

const sections: Record<KnowledgeSection, { title: string; description: string }> = {
  overview: { title: "Overview", description: "Monitor the knowledge base and find what needs attention." },
  documents: { title: "Documents", description: "Manage the company sources used in assistant answers." },
  quality: { title: "Answer quality", description: "Review employee feedback and questions that need better sources." },
  settings: { title: "AI settings", description: "Prepare, test and apply changes to future assistant answers." },
  integrations: { title: "Integrations", description: "Manage private request notifications in Slack and Discord." },
};

export function KnowledgePage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("section");
  const section: KnowledgeSection = requested && Object.prototype.hasOwnProperty.call(sections, requested) ? requested as KnowledgeSection : "overview";
  const heading = useRef<HTMLHeadingElement>(null);
  const previousSection = useRef(section);
  useEffect(() => {
    if (previousSection.current === section) return;
    previousSection.current = section;
    heading.current?.focus({preventScroll: true});
    window.scrollTo({top: 0});
  }, [section]);
  const metrics = useKnowledgeMetrics();
  const navigate = (next: KnowledgeSection) => setParams(current => {
    const updated = new URLSearchParams(current);
    updated.set("section", next);
    return updated;
  });

  return <Shell title={sections[section].title} eyebrow="Knowledge admin">
    <div className="workspace-page knowledge-workspace space-y-4">
      <PageHeader headingRef={heading} title={sections[section].title} description={sections[section].description}
        actions={section === "overview" && <Button tone="secondary" disabled={metrics.isFetching} onClick={() => void metrics.refetch()}><RefreshCw size={16} aria-hidden="true"/>{metrics.isFetching ? "Refreshing…" : "Refresh"}</Button>}/>
      {section === "overview" && <OverviewSection metrics={metrics.data?.metrics} loading={metrics.isLoading} error={metrics.isError} onRetry={() => void metrics.refetch()} onNavigate={navigate}/>}
      {section === "documents" && <DocumentsSection/>}
      {section === "quality" && <QualitySection metrics={metrics.isError ? undefined : metrics.data?.metrics} onNavigate={navigate}/>}
      {section === "settings" && <SettingsSection/>}
      {section === "integrations" && <IntegrationsSection/>}
    </div>
  </Shell>;
}

