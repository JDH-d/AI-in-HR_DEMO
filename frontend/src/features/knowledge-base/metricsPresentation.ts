import type { Metrics } from "../../api/types";

export function feedbackCount(metrics?: Metrics): number | undefined {
  if (!metrics || typeof metrics.feedback !== "number" || typeof metrics.assistant_feedback !== "number") return undefined;
  return metrics.feedback + metrics.assistant_feedback;
}

export function helpfulRatings(metrics?: Metrics): string {
  if (!metrics) return "Unavailable";
  return feedbackCount(metrics) === 0 ? "No ratings yet" : `${metrics.positive_feedback_rate}%`;
}
