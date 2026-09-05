import {
  ArrowsClockwise,
  BookOpen,
  ChartBar,
  ChatCircleDots,
  type Icon,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import type { Metrics } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Button, Card } from "../../components/ui";
import { AISettingsPanel } from "./AISettingsPanel";
import { DocumentsPanel } from "./DocumentsPanel";
import { KnowledgeOverview } from "./KnowledgeOverview";
import { QualityPanel } from "./QualityPanel";

type Section = "overview" | "documents" | "quality" | "settings";

const navigation: { id: Section; label: string; icon: Icon }[] = [
  { id: "overview", label: "Overview", icon: ChartBar },
  { id: "documents", label: "Documents", icon: BookOpen },
  { id: "quality", label: "Quality", icon: ChatCircleDots },
  { id: "settings", label: "AI settings", icon: SlidersHorizontal },
];

const descriptions: Record<Section, string> = {
  overview: "A quick view of employee questions, answer quality, and requests.",
  documents: "Manage the company policies and documents your assistant uses.",
  quality: "Review employee feedback and questions that need better sources.",
  settings: "Adjust how the assistant responds and try changes before applying them.",
};

export function KnowledgePage() {
  const { token } = useAuth();
  const [section, setSection] = useState<Section>("overview");
  const [settingsVisited, setSettingsVisited] = useState(false);
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<{ metrics: Metrics }>("/api/v1/admin/metrics", token),
  });
  const title = navigation.find((item) => item.id === section)?.label ?? "Knowledge operations";

  const sidebar = (
    <nav aria-label="Knowledge operations" className="space-y-1">
      {navigation.map(({ id, label, icon: Icon }) => (
        <button
          type="button"
          key={id}
          onClick={() => {
            setSection(id);
            if (id === "settings") setSettingsVisited(true);
          }}
          aria-current={section === id ? "page" : undefined}
          className={`focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm transition ${section === id ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-raised hover:text-cream"}`}
        >
          <Icon size={20} />
          {label}
        </button>
      ))}
    </nav>
  );

  return (
    <Shell sidebar={sidebar} eyebrow="Knowledge operations">
      <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted">{descriptions[section]}</p>
          </div>
          {section === "overview" && (
            <Button
              tone="secondary"
              onClick={() => metrics.refetch()}
              disabled={metrics.isFetching}
            >
              <ArrowsClockwise size={18} className={metrics.isFetching ? "animate-spin" : ""} />
              Refresh
            </Button>
          )}
        </div>

        {section === "overview" && metrics.isLoading && (
          <Card className="grid min-h-64 place-items-center text-sm text-muted">
            Loading knowledge metrics…
          </Card>
        )}
        {section === "overview" && metrics.isError && (
          <Card className="grid min-h-64 place-items-center text-center">
            <div>
              <p className="font-semibold">Unable to load knowledge metrics</p>
              <p className="mt-2 text-sm text-muted">
                The latest workspace summary is unavailable.
              </p>
              <Button className="mt-5" tone="secondary" onClick={() => metrics.refetch()}>
                <ArrowsClockwise size={18} />
                Try again
              </Button>
            </div>
          </Card>
        )}
        {section === "overview" && metrics.isSuccess && (
          <KnowledgeOverview metrics={metrics.data.metrics} />
        )}
        {section === "documents" && <DocumentsPanel />}
        {section === "quality" && (
          <QualityPanel
            metrics={metrics.data?.metrics}
            onAddSource={() => setSection("documents")}
          />
        )}
        {settingsVisited && (
          <div hidden={section !== "settings"}>
            <AISettingsPanel />
          </div>
        )}
      </div>
    </Shell>
  );
}
