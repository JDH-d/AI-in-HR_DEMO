import {
  ChartBar,
  CheckCircle,
  FileText,
  type Icon,
  ThumbsUp,
  Warning,
} from "@phosphor-icons/react";
import type { Metrics } from "../../api/types";
import { Card } from "../../components/ui";

export function KnowledgeOverview({ metrics }: { metrics?: Metrics }) {
  const cards: Array<{
    label: string;
    metric: string | number;
    copy: string;
    icon: Icon;
    iconClassName: string;
  }> = [
    {
      label: "Questions",
      metric: metrics?.questions ?? 0,
      copy: "Employee questions received",
      icon: ChartBar,
      iconClassName: "text-accent",
    },
    {
      label: "Grounded rate",
      metric: `${metrics?.grounded_answer_rate ?? 0}%`,
      copy: "Answers with document evidence",
      icon: CheckCircle,
      iconClassName: "text-success",
    },
    {
      label: "Unanswered",
      metric: metrics?.unanswered_questions ?? 0,
      copy: "Knowledge gaps to resolve",
      icon: Warning,
      iconClassName: "text-warning",
    },
    {
      label: "Positive feedback",
      metric: `${metrics?.positive_feedback_rate ?? 0}%`,
      copy: "Helpful response ratings",
      icon: ThumbsUp,
      iconClassName: "text-success",
    },
    {
      label: "Requests created",
      metric: metrics?.requests_created ?? 0,
      copy: "Employee actions started",
      icon: FileText,
      iconClassName: "text-accent",
    },
    {
      label: "Approved",
      metric: metrics?.requests_approved ?? 0,
      copy: "Requests approved by managers",
      icon: CheckCircle,
      iconClassName: "text-success",
    },
  ];

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-sm font-semibold">Workspace activity</h2>
      </div>
      <dl className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-3">
        {cards.map(({ label, metric, copy, icon: MetricIcon, iconClassName }) => (
          <div key={label} className="bg-panel p-5">
            <dt className="flex items-center gap-2 text-sm text-muted">
              <MetricIcon size={18} className={iconClassName} />
              {label}
            </dt>
            <dd className="mt-3">
              <span className="text-2xl font-semibold tracking-tight tabular-nums">{metric}</span>
              <p className="mt-1.5 text-sm leading-6 text-muted">{copy}</p>
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
