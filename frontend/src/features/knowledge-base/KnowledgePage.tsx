import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  type LucideIcon,
  MessageSquareWarning,
  RefreshCw,
  Settings2,
} from "lucide-react";
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

const navigation: { id: Section; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: BarChart3 },
  { id: "documents", label: "Documents", icon: BookOpen },
  { id: "quality", label: "Quality", icon: MessageSquareWarning },
  { id: "settings", label: "AI settings", icon: Settings2 },
];

export function KnowledgePage() {
  const { token } = useAuth();
  const [section, setSection] = useState<Section>("overview");
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
          onClick={() => setSection(id)}
          className={`focus-ring flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm ${section === id ? "bg-lime-soft text-lime" : "text-muted hover:bg-raised hover:text-cream"}`}
        >
          <Icon className="h-4 w-4" />
          {label}
        </button>
      ))}
    </nav>
  );

  return (
    <Shell sidebar={sidebar} eyebrow="Knowledge operations">
      <div className="mx-auto max-w-7xl p-4 sm:p-8">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.18em] text-lime">
              Knowledge health
            </p>
            <h1 className="mt-3 text-4xl font-medium tracking-[-.035em]">{title}</h1>
          </div>
          {section === "overview" && (
            <Button tone="secondary" onClick={() => metrics.refetch()}>
              <RefreshCw size={15} />
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
                <RefreshCw size={15} />
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
        {section === "settings" && <AISettingsPanel />}
      </div>
    </Shell>
  );
}
