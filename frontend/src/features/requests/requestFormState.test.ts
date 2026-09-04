import { describe, expect, it } from "vitest";
import { buildRequestPayload, deriveRequestForm, type RequestFormValues } from "./requestFormState";

const pto: RequestFormValues = {
  type: "pto",
  start: "2030-04-10",
  end: "2030-04-12",
  comment: "Handoff is ready.",
  returnMode: "default",
  customReturn: "",
  timeAway: "full_day",
  partialHours: "4",
  extendedOrRecurring: false,
};

describe("request form state", () => {
  it("derives a calendar-safe PTO duration and clean payload", () => {
    const derived = deriveRequestForm(pto);

    expect(derived.duration).toBe(3);
    expect(derived.formIsReady).toBe(true);
    expect(buildRequestPayload(pto, derived.expectedReturn)).toEqual({
      type: "pto",
      start_date: "2030-04-10",
      end_date: "2030-04-12",
      comment: "Handoff is ready.",
      details: {},
    });
  });

  it("represents an unknown sick-leave return without inventing an end date", () => {
    const sickLeave: RequestFormValues = {
      ...pto,
      type: "sick_leave",
      start: "2030-04-10",
      end: "",
      comment: "",
      returnMode: "unknown",
      timeAway: "partial_day",
      partialHours: "3.5",
      extendedOrRecurring: true,
    };
    const derived = deriveRequestForm(sickLeave);

    expect(derived.formIsReady).toBe(true);
    expect(buildRequestPayload(sickLeave, derived.expectedReturn)).toEqual({
      type: "sick_leave",
      start_date: "2030-04-10",
      end_date: null,
      comment: "",
      details: {
        expected_return_date: null,
        expected_return_unknown: true,
        time_away: "partial_day",
        partial_hours: 3.5,
        extended_or_recurring: true,
      },
    });
  });

  it("does not allow invalid partial-day hours", () => {
    const derived = deriveRequestForm({
      ...pto,
      type: "sick_leave",
      returnMode: "default",
      timeAway: "partial_day",
      partialHours: "0",
    });

    expect(derived.formIsReady).toBe(false);
  });
});
