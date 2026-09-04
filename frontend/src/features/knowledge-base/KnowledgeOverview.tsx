import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  FileText,
  type LucideIcon,
  ThumbsUp,
} from "lucide-react";
import type { Metrics } from "../../api/types";
import { Card } from "../../components/ui";

export function KnowledgeOverview({ metrics }: { metrics?: Metrics }) {
  const cards: Array<{
    label: string;
    metric: string | number;
    copy: string;
    icon: LucideIcon;
  }> = [
    {
      label: "Questions",
      metric: metrics?.questions ?? 0,
      copy: "Employee questions received",
      icon: BarChart3,
    },
    {
      label: "Grounded rate",
      metric: `${metrics?.grounded_answer_rate ?? 0}%`,
      copy: "Answers with document evidence",
      icon: CheckCircle2,
    },
    {
      label: "Unanswered",
      metric: metrics?.unanswered_questions ?? 0,
      copy: "Knowledge gaps to resolve",
      icon: AlertTriangle,
    },
    {
      label: "Positive feedback",
      metric: `${metrics?.positive_feedback_rate ?? 0}%`,
      copy: "Helpful response ratings",
      icon: ThumbsUp,
    },
    {
      label: "Requests created",
      metric: metrics?.requests_created ?? 0,
      copy: "Employee actions started",
      icon: FileText,
    },
    {
      label: "Approved",
      metric: metrics?.requests_approved ?? 0,
      copy: "Requests approved by managers",
      icon: CheckCircle2,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map(({ label, metric, copy, icon: Icon }) => (
        <Card key={label} className="min-h-40">
          <div className="flex items-start justify-between">
            <span className="text-sm font-semibold">{label}</span>
            <Icon className="text-lime" size={20} />
          </div>
          <strong className="mt-7 block text-4xl font-medium tracking-tight">{metric}</strong>
          <p className="mt-2 text-xs text-muted">{copy}</p>
        </Card>
      ))}
    </div>
  );
}
