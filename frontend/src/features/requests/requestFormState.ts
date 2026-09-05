import { useMemo, useState } from "react";
import type { RequestType, WorkflowRequest } from "../../api/types";
import {
  addIsoDays,
  getSickLeaveDetails,
  type SickTimeAway,
  todayIso,
} from "./requestPresentation";

export type ReturnMode = "default" | "date" | "unknown";

export type RequestFormValues = {
  type: RequestType;
  start: string;
  end: string;
  comment: string;
  returnMode: ReturnMode;
  customReturn: string;
  timeAway: SickTimeAway;
  partialHours: string;
  extendedOrRecurring: boolean;
};

export type RequestPayload = {
  type: RequestType;
  start_date: string | null;
  end_date: string | null;
  comment: string;
  details: Record<string, unknown>;
};

const emptyForm: RequestFormValues = {
  type: "pto",
  start: "",
  end: "",
  comment: "",
  returnMode: "default",
  customReturn: "",
  timeAway: "full_day",
  partialHours: "4",
  extendedOrRecurring: false,
};

export function useRequestForm(initial: WorkflowRequest | null | undefined) {
  const [initialValues] = useState<RequestFormValues>(() => valuesFromRequest(initial));
  const [values, setValues] = useState<RequestFormValues>(initialValues);

  const derived = useMemo(() => deriveRequestForm(values), [values]);

  const update = (patch: Partial<RequestFormValues>) => {
    setValues((current) => ({ ...current, ...patch }));
  };

  const changeType = (type: RequestType) => {
    setValues((current) => ({
      ...current,
      type,
      start: type === "sick_leave" && !current.start ? todayIso() : current.start,
    }));
  };

  const changeStart = (start: string) => {
    setValues((current) => ({
      ...current,
      start,
      end:
        current.type === "pto" && start && (!current.end || current.end < start)
          ? start
          : current.end,
    }));
  };

  const choosePtoLength = (days: number) => {
    if (values.start) update({ end: addIsoDays(values.start, days - 1) });
  };

  return {
    values,
    isDirty: JSON.stringify(values) !== JSON.stringify(initialValues),
    ...derived,
    update,
    changeType,
    changeStart,
    choosePtoLength,
    payload: buildRequestPayload(values, derived.expectedReturn),
  };
}

export function valuesFromRequest(initial: WorkflowRequest | null | undefined): RequestFormValues {
  if (!initial) return { ...emptyForm };

  const sickLeave = getSickLeaveDetails(initial);
  const defaultReturn = initial.start_date
    ? addIsoDays(initial.start_date, sickLeave.timeAway === "partial_day" ? 0 : 1)
    : "";
  const returnMode: ReturnMode = sickLeave.expectedReturnUnknown
    ? "unknown"
    : !sickLeave.expectedReturnDate || sickLeave.expectedReturnDate === defaultReturn
      ? "default"
      : "date";

  return {
    type: initial.type,
    start: initial.start_date ?? "",
    end: initial.end_date ?? "",
    comment: initial.comment,
    returnMode,
    customReturn: returnMode === "date" ? (sickLeave.expectedReturnDate ?? "") : "",
    timeAway: sickLeave.timeAway,
    partialHours: String(sickLeave.partialHours ?? 4),
    extendedOrRecurring: sickLeave.extendedOrRecurring,
  };
}

export function deriveRequestForm(values: RequestFormValues) {
  const isSickLeave = values.type === "sick_leave";
  const defaultReturn = values.start
    ? addIsoDays(values.start, values.timeAway === "partial_day" ? 0 : 1)
    : "";
  const expectedReturn =
    values.returnMode === "unknown"
      ? null
      : values.returnMode === "default"
        ? defaultReturn
        : values.customReturn || null;
  const parsedHours = Number(values.partialHours);
  const returnIsValid =
    values.returnMode === "unknown" ||
    Boolean(
      values.start &&
        expectedReturn &&
        (values.timeAway === "partial_day"
          ? expectedReturn >= values.start
          : expectedReturn > values.start),
    );
  const hoursAreValid =
    values.timeAway === "full_day" ||
    (Number.isFinite(parsedHours) && parsedHours > 0 && parsedHours <= 24);
  const ptoDatesAreValid = Boolean(values.start && values.end && values.end >= values.start);
  const duration = ptoDatesAreValid ? isoDayDifference(values.start, values.end) + 1 : null;
  const formIsReady = isSickLeave
    ? Boolean(values.start && returnIsValid && hoursAreValid)
    : Boolean(values.comment.trim() && ptoDatesAreValid);

  return {
    isSickLeave,
    defaultReturn,
    expectedReturn,
    parsedHours,
    returnIsValid,
    hoursAreValid,
    ptoDatesAreValid,
    duration,
    formIsReady,
  };
}

export function buildRequestPayload(
  values: RequestFormValues,
  expectedReturn: string | null,
): RequestPayload {
  const sickLeaveEnd =
    values.start && expectedReturn
      ? ([values.start, addIsoDays(expectedReturn, -1)].sort().at(-1) ?? values.start)
      : null;
  const parsedHours = Number(values.partialHours);

  return {
    type: values.type,
    start_date: values.start || null,
    end_date: values.type === "sick_leave" ? sickLeaveEnd : values.end || null,
    comment: values.comment.trim(),
    details:
      values.type === "sick_leave"
        ? {
            expected_return_date: expectedReturn,
            expected_return_unknown: values.returnMode === "unknown",
            time_away: values.timeAway,
            partial_hours: values.timeAway === "partial_day" ? parsedHours : null,
            extended_or_recurring: values.extendedOrRecurring,
          }
        : {},
  };
}

function isoDayDifference(start: string, end: string): number {
  const [startYear, startMonth, startDay] = start.split("-").map(Number);
  const [endYear, endMonth, endDay] = end.split("-").map(Number);
  return Math.round(
    (Date.UTC(endYear, endMonth - 1, endDay) - Date.UTC(startYear, startMonth - 1, startDay)) /
      86_400_000,
  );
}
