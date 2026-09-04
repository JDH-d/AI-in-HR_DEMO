import type { WorkflowRequest } from "../../api/types";

export type SickTimeAway = "full_day" | "partial_day";

export type SickLeaveDetails = {
  expectedReturnDate: string | null;
  expectedReturnUnknown: boolean;
  timeAway: SickTimeAway;
  partialHours: number | null;
  extendedOrRecurring: boolean;
};

export function addIsoDays(value: string, amount: number): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return "";
  const date = new Date(year, month - 1, day + amount);
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

export function todayIso(now = new Date()): string {
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
}

export function getSickLeaveDetails(request: WorkflowRequest): SickLeaveDetails {
  const details = request.details ?? {};
  const expectedReturnUnknown = details.expected_return_unknown === true;
  const explicitReturn =
    typeof details.expected_return_date === "string" ? details.expected_return_date : null;
  const inferredReturn =
    !expectedReturnUnknown && request.end_date ? addIsoDays(request.end_date, 1) : null;
  const partialHours = typeof details.partial_hours === "number" ? details.partial_hours : null;

  return {
    expectedReturnDate: explicitReturn || inferredReturn,
    expectedReturnUnknown,
    timeAway: details.time_away === "partial_day" ? "partial_day" : "full_day",
    partialHours,
    extendedOrRecurring: details.extended_or_recurring === true,
  };
}

export function formatRequestDate(value: string | null): string {
  if (!value) return "Not set";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Date(year, month - 1, day).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function expectedReturnLabel(request: WorkflowRequest): string {
  const details = getSickLeaveDetails(request);
  return details.expectedReturnUnknown
    ? "Not sure yet"
    : formatRequestDate(details.expectedReturnDate);
}

export function timeAwayLabel(request: WorkflowRequest): string {
  const details = getSickLeaveDetails(request);
  if (details.timeAway === "partial_day") {
    return details.partialHours ? `${details.partialHours} hours` : "Partial day";
  }
  return request.duration_days
    ? `${request.duration_days} full ${request.duration_days === 1 ? "day" : "days"}`
    : "Full day";
}

export function requestPeriodLabel(request: WorkflowRequest): string {
  if (request.type === "sick_leave") {
    return `${formatRequestDate(request.start_date)} · back ${expectedReturnLabel(request)}`;
  }
  if (!request.start_date && !request.end_date) return "No dates";
  return `${formatRequestDate(request.start_date)} → ${formatRequestDate(request.end_date)}`;
}
