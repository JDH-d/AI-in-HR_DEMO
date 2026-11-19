/** Presentation only: API status values and workflow rules stay unchanged. */
export function requestLabel(value: string): string {
  const words = value.replaceAll("_", " ");
  return words ? words[0].toUpperCase() + words.slice(1) : words;
}

export function requestDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value));
}

export function nextStep(status: string, manager: boolean): string {
  const employeeSteps: Record<string, string> = {
    draft: "Private draft — finish it when you are ready.",
    submitted: "Your manager will review this request.",
    in_review: "Your manager is reviewing this request.",
    needs_information: "Your manager needs more information. Read the request below and reply.",
    approved: "Read the decision and any next steps below.",
    rejected: "Read the reason below. You can ask for reconsideration.",
    cancelled: "This request is cancelled. Its history is still available.",
    completed: "This request is complete. The decision and history remain available.",
  };
  const managerSteps: Record<string, string> = {
    submitted: "Start a review to make a decision or ask for information.",
    in_review: "Review the details, then approve, reject or request information.",
    needs_information: "Waiting for the employee's reply. You can review the discussion below.",
    approved: "Mark this request complete once the approved work is finished.",
    rejected: "Your decision is recorded and visible to the employee.",
    cancelled: "The employee cancelled this request. No review action is needed.",
    completed: "This request is complete. No review action is needed.",
  };
  return (manager ? managerSteps : employeeSteps)[status] ?? "Review the request details below.";
}

/** Stages describe review progress, not a promise that a request will be approved. */
export function employeeRequestStage(status: string): { current: number | null; title: string; stages: string[] } {
  const stages = ["Draft", "Submitted", "Review", "Decision"];
  const known: Record<string, { current: number | null; title: string }> = {
    draft: { current: 0, title: "Finish your draft" },
    submitted: { current: 1, title: "Waiting for review" },
    in_review: { current: 2, title: "Your manager is reviewing it" },
    needs_information: { current: 2, title: "Your reply is needed" },
    approved: { current: 3, title: "Your request was approved" },
    rejected: { current: 3, title: "Your request was rejected" },
    completed: { current: 4, title: "Your request is complete" },
    cancelled: { current: null, title: "Your request is cancelled" },
  };
  if (["approved", "completed"].includes(status)) stages.push("Completed");
  return { ...(known[status] ?? { current: null, title: "Request status" }), stages };
}
