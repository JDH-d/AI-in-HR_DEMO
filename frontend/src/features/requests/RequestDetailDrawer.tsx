import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, Check, ChevronDown, MessageSquareText, RefreshCw, UserRoundCog, X } from "lucide-react";
import { useAuth } from "../../app/providers";
import { Badge, Button, Drawer, LoadingSkeleton, fieldClass, statusTone } from "../../components/ui";
import { useUnsavedChanges } from "../../components/UnsavedChanges";
import { DecisionNote, EmployeeRequestProgress, RequestOverview, RequestTimeline } from "./RequestDetails";
import { RequestDrawer } from "./RequestDrawer";
import { useRequestActions } from "./useRequestActions";
import { useRequestOptions } from "./useRequests";
import { nextStep, requestDate, requestLabel } from "./requestPresentation";
import { hasTemplatePlaceholders, ReplyTemplates } from "./ReplyTemplates";
import "./requests.css";

export const actionLabels: Record<string, string> = {
  start_review: "Start review", request_information: "Request information", provide_information: "Provide information",
  approve: "Approve", reject: "Reject", cancel: "Cancel request", complete: "Mark completed", appeal: "Request reconsideration",
};
export const requestNumber = (number: number) => `REQ-${String(number).padStart(6, "0")}`;

export function RequestDetailDrawer({ id, onClose, presentation = "dialog" }: { id: string | null; onClose: () => void; presentation?: "dialog" | "page" }) {
  const { user } = useAuth();
  const employee = user?.role === "employee";
  const { detail, mutation, download } = useRequestActions(id);
  const options = useRequestOptions();
  const [editing, setEditing] = useState(false);
  const [action, setAction] = useState("");
  const [actionOpen, setActionOpen] = useState(false);
  const [discardAction, setDiscardAction] = useState(false);
  const [reason, setReason] = useState("");
  const [basis, setBasis] = useState("");
  const [fair, setFair] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [comment, setComment] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [downloadError, setDownloadError] = useState("");
  const [assignee, setAssignee] = useState("");
  const [assignmentReason, setAssignmentReason] = useState("");
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [confirmReassignment, setConfirmReassignment] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const successRevision = useRef<number | undefined>(undefined);
  const errorNotice = useRef<HTMLParagraphElement>(null);
  const dirty = Boolean(reason.trim() || basis.trim() || comment.trim() || file || assignee || assignmentReason.trim());
  const clearUnsavedChanges = useUnsavedChanges(Boolean(id) && !editing && dirty);
  const close = () => {
    if (mutation.isPending) return;
    if (dirty) setDiscardOpen(true); else onClose();
  };
  const reviewedRevision = useRef<number | undefined>(undefined);
  const [changedDuringReview, setChangedDuringReview] = useState(false);
  useEffect(() => {
    setAction(""); setReason(""); setBasis(""); setFair(false); setConfirm(false);
    setComment(""); setFile(null); setFileKey(value => value + 1); setDownloadError(""); setEditing(false); setAssignee(""); setAssignmentReason("");
    mutation.reset();
    reviewedRevision.current = undefined; setChangedDuringReview(false);
    setDiscardOpen(false); setConfirmReassignment(false); setSuccessMessage(""); successRevision.current = undefined;
    setAssignmentOpen(false);
    setActionOpen(false); setDiscardAction(false);
  }, [id]);
  const unavailable = Boolean(detail.error && "status" in detail.error && [403, 404].includes(Number(detail.error.status)));
  const request = unavailable ? undefined : detail.data?.request;
  const clearSuccess = () => { setSuccessMessage(""); successRevision.current = undefined; };
  const showSuccess = (message: string, result: unknown) => {
    const saved = result && typeof result === "object" && "request" in result ? result.request : undefined;
    successRevision.current = saved && typeof saved === "object" && "revision" in saved && typeof saved.revision === "number" ? saved.revision : reviewedRevision.current;
    setSuccessMessage(message);
  };
  useEffect(() => {
    if (reviewedRevision.current !== undefined && request?.revision !== undefined && reviewedRevision.current !== request.revision) {
      setFair(false); setConfirm(false); setConfirmReassignment(false);
      // A new revision is only a conflict notice while there is unsent work to
      // review. Read-only refreshes and the draft editor's own save are normal.
      setChangedDuringReview(dirty && !editing && !mutation.isPending);
    }
    reviewedRevision.current = request?.revision;
  }, [id, request?.revision]);
  useEffect(() => {
    if (detail.isError || mutation.error || downloadError || (successRevision.current !== undefined && request?.revision !== undefined && successRevision.current !== request.revision)) {
      setSuccessMessage(""); successRevision.current = undefined;
    }
  }, [request?.revision, detail.isError, mutation.error, downloadError, successMessage]);
  useEffect(() => {
    if (mutation.error || downloadError) {
      errorNotice.current?.focus();
      errorNotice.current?.scrollIntoView?.({ block: "nearest" });
    }
  }, [mutation.error, downloadError]);
  const actions = detail.data?.allowed_actions.filter(item => item !== "submit") ?? [];
  const selectedAction = actions.includes(action) ? action : "";
  const showingAction = Boolean(actionOpen && selectedAction && request);
  const decision = ["approve", "reject"].includes(action);
  const actionLabel = (item: string) => employee && item === "provide_information" ? "Reply to manager" : actionLabels[item];
  const submitLabel = employee && action === "provide_information" ? "Send reply" : actionLabels[action];
  const reasonLabel = !employee ? "Reason or additional information *" : action === "provide_information" ? "Your response *" : action === "appeal" ? "Reason for reconsideration *" : action === "cancel" ? "Reason for cancellation *" : "Reason or additional information *";
  const requiresReason = action !== "start_review";
  const disabled = mutation.isPending || detail.isFetching || detail.isError;
  const incompleteTemplate = user?.role === "manager" && (hasTemplatePlaceholders(reason) || hasTemplatePlaceholders(basis));
  const valid = Boolean(actions.includes(action) && (!requiresReason || reason.trim().length >= 3) && !incompleteTemplate && (!decision || (basis.trim().length >= 3 && fair)));
  const record = async (requestedAction = action) => {
    if (disabled || !actions.includes(requestedAction) || (requestedAction !== "start_review" && !valid)) return;
    clearSuccess();
    try {
      const result = await mutation.mutateAsync({ path: `actions/${requestedAction}`, body: { comment: requestedAction === "start_review" ? "" : reason, basis, fair_review_confirmed: fair } });
      showSuccess(employee && requestedAction === "provide_information" ? "Your reply was sent to the assigned manager. The request is back in review." : employee && requestedAction === "appeal" ? "Reconsideration requested. The original decision is preserved in the history." : employee && requestedAction === "cancel" ? "Request cancelled. The saved request and history remain available." : `${actionLabels[requestedAction]} recorded. The request and history are up to date.`, result);
      setChangedDuringReview(false);
      setAction(""); setReason(""); setBasis(""); setFair(false); setConfirm(false);
      setActionOpen(false);
    } catch { setConfirm(false); setFair(false); }
  };
  const otherManagers = options.data?.managers?.filter(item => item.id !== request?.approver && item.id !== request?.applicant) ?? [];
  const assignmentDisabled = disabled || options.isError || options.isFetching;
  const assignmentTargetAvailable = otherManagers.some(item => item.id === assignee);
  const unavailableAssignee = Boolean(assignee && options.isSuccess && !assignmentTargetAvailable);
  const canReassign = !assignmentDisabled && assignmentTargetAvailable && assignmentReason.trim().length >= 3;
  useEffect(() => {
    if (unavailableAssignee || options.isError) setConfirmReassignment(false);
  }, [unavailableAssignee, options.isError]);
  const otherUnsentWork = Boolean(reason.trim() || basis.trim() || comment.trim() || file);
  const reassign = async () => {
    if (!canReassign) return;
    clearSuccess();
    try {
      await mutation.mutateAsync({ path: "assign", body: { assignee, comment: assignmentReason } });
      clearUnsavedChanges(); onClose();
    } catch { setConfirmReassignment(false); }
  };
  const active = request && !["approved", "rejected", "completed", "cancelled"].includes(request.status);
  const latestInformationRequest = request?.status === "needs_information"
    ? [...(detail.data?.events ?? [])].reverse().find(event => event.to_status === "needs_information" &&
      (event.event_type === "request_information" || (event.event_type === "status_changed" && event.from_status !== "needs_information")) &&
      typeof event.details.comment === "string" && event.details.comment.trim())
    : undefined;
  const closeAction = () => {
    if (mutation.isPending) return;
    setActionOpen(false); setConfirm(false); setFair(false);
    if (!reason.trim() && !basis.trim()) setAction("");
  };
  const changeNotice = <p role="status" className="rounded-lg border border-line p-3 text-sm">The request changed. Your unsent text is kept. Review the latest information before continuing.{user?.role === "manager" && " Decisions need fresh confirmation."}</p>;
  const actionButton = (item: string) => <Button key={item} disabled={disabled} tone={["reject", "cancel"].includes(item) ? "danger" : ["start_review", "approve", "provide_information", "appeal", "complete"].includes(item) ? "primary" : "secondary"} onClick={() => { clearSuccess(); if (item === "start_review") void record(item); else { setAction(item); setActionOpen(true); setConfirm(false); setFair(false); } }}>
    {item === "approve" ? <Check size={16} aria-hidden="true"/> : item === "reject" || item === "cancel" ? <X size={16} aria-hidden="true"/> : item.includes("information") ? <MessageSquareText size={16} aria-hidden="true"/> : null}{actionLabel(item)}
  </Button>;
  return <>
    <RequestSurface open={Boolean(id) && !editing} onClose={close} presentation={presentation} title={request?.title || "Request details"}>
      {detail.isLoading && <LoadingSkeleton label="Loading request…" rows={3}/>}
      {detail.isError && <div role="alert" className="rounded-xl border border-danger/30 bg-danger/10 p-4 text-sm text-danger"><p>{unavailable ? "This request is no longer available to you. Return to your request list or reload to check your access." : detail.data ? "This request could not be refreshed. Previously loaded information is shown below; reload successfully before making changes." : "Unable to load this request. Check your connection and try again."}</p><Button tone="secondary" className="mt-3" onClick={() => void detail.refetch()}>Reload request</Button></div>}
      {detail.data && request && <div className="request-detail-content space-y-4 [overflow-wrap:anywhere]">
        <div className="request-status-line"><Badge tone={statusTone(request.status)}>{requestLabel(request.status)}</Badge><span className="text-xs text-muted">{requestNumber(request.number)} · Review {request.review_round}</span><Button tone="ghost" className="request-refresh" aria-label="Refresh request" title="Refresh request" disabled={disabled} onClick={() => { clearSuccess(); setFair(false); setConfirm(false); void detail.refetch(); }}><RefreshCw size={16} aria-hidden="true"/><span>Refresh</span></Button></div>
        {employee && <EmployeeRequestProgress detail={detail.data} informationRequest={latestInformationRequest}/>}
        {user?.role === "manager" && request.manager_attention && ["submitted", "in_review", "needs_information"].includes(request.status) && <section aria-label="Review target" className={`rounded-lg border p-3 text-sm ${request.manager_attention.overdue ? "border-danger/30 bg-danger/10" : "border-line bg-panel"}`}>
          <h3 className="font-semibold">{request.status === "needs_information" ? "Review paused — waiting for employee" : request.manager_attention.overdue ? "Review overdue" : "Review target"}</h3>
          {request.manager_attention.due_at && <p className="mt-1">Review by <time dateTime={request.manager_attention.due_at}>{requestDate(request.manager_attention.due_at)}</time>.</p>}
          <p className="mt-1 text-xs leading-5 text-muted">Allow 5 calendar days after submission, reconsideration or the employee's reply. Waiting for the employee is not counted as overdue review. Reassignment does not restart the target.</p>
        </section>}
        {(!employee || actions.length > 0 || request.status === "draft") && <div className="request-action-strip">
          {!employee && <p className="text-sm leading-5 text-muted">{nextStep(request.status, user?.role === "manager")}</p>}
          {(actions.length > 0 || (request.status === "draft" && user?.role === "employee")) && <section aria-label="Available actions" className="request-action-controls">
            {!selectedAction ? <>
              {request.status === "draft" && user?.role === "employee" && <Button disabled={disabled} onClick={() => { clearSuccess(); setEditing(true); }}>Edit or submit draft</Button>}
              {actions.filter(item => item !== "cancel").map(actionButton)}
              {actions.includes("cancel") && <div className="request-destructive-action"><span className="sr-only">Manage request</span>{actionButton("cancel")}</div>}
            </> : <>
              <p className="request-unsent-note text-xs text-muted">{employee ? "Your text has not been sent." : `Unsent notes for ${actionLabels[action]}`}</p><Button disabled={disabled} onClick={() => { clearSuccess(); setActionOpen(true); }}>{employee && action === "provide_information" ? "Continue reply" : `Continue ${actionLabels[action]}`}</Button><Button tone="ghost" disabled={disabled} onClick={() => setDiscardAction(true)}>{employee ? "Discard unsent text" : "Discard review notes"}</Button>
            </>}
          </section>}
        </div>}
        {successMessage && !detail.isError && !mutation.error && !downloadError && (successRevision.current === undefined || successRevision.current === request.revision) && <p role="status" className="success-feedback rounded-lg border border-lime/30 bg-lime-soft p-3 text-sm">{successMessage}</p>}
        {changedDuringReview && !showingAction && changeNotice}
        {action && !selectedAction && (reason.trim() || basis.trim()) && <section aria-label="Unsent review notes" className="space-y-2 rounded-lg border border-line p-4 text-sm"><h3 className="font-semibold">Your unsent notes</h3><p className="text-muted">This action is no longer available. These notes were not submitted.</p><p className="whitespace-pre-wrap">{reason}</p>{basis && <p className="whitespace-pre-wrap">{basis}</p>}</section>}
        <DecisionNote detail={detail.data}/>
        {employee && actions.includes("appeal") && <section aria-label="About reconsideration" className="employee-reconsideration"><h3>Want this decision reviewed again?</h3><p>You can request reconsideration of an approved, rejected or completed request. Explain what should change or provide relevant information. The same assigned manager reviews it again; the original decision stays in the history.</p></section>}
        {!employee && latestInformationRequest && <section aria-label="Information requested" className="rounded-xl border border-coral/30 bg-coral/10 p-4"><h3 className="font-semibold">Information requested</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-6">{String(latestInformationRequest.details.comment)}</p></section>}
        <section aria-label="Request details" className="request-summary rounded-lg border border-line bg-panel">
          <section aria-label="Request description" className="request-description"><h3 className="text-sm font-semibold">Description</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-6">{request.comment || "No description added yet."}</p></section>
          <div className="request-metadata"><RequestOverview request={request} managerName={options.data?.managers?.find(item => item.id === request.approver)?.display_name}/></div>
          {user?.role === "manager" && active && options.isError && <div role="alert" className="space-y-2 border-t border-line p-4 text-sm"><p>The list of managers could not be loaded. Retry to change the assigned manager; your other review actions are still available.</p><Button tone="secondary" disabled={options.isFetching} onClick={() => void options.refetch()}>Retry manager list</Button></div>}
          {user?.role === "manager" && active && options.isSuccess && !otherManagers.length && <p className="border-t border-line p-4 text-sm text-muted">No other manager is currently available for reassignment. This request stays with its assigned manager.</p>}
          {user?.role === "manager" && active && unavailableAssignee && <p id="reassignment-target-error" role="alert" className="border-t border-line p-4 text-sm text-danger">The selected manager is no longer available for reassignment. Choose another manager when available; your reason is kept.</p>}
          {user?.role === "manager" && active && otherManagers.length > 0 && <section aria-label="Assignment" className="request-assignment"><Button tone="ghost" className="justify-between" aria-expanded={assignmentOpen} aria-controls="reassignment-form" onClick={() => setAssignmentOpen(value => !value)}><span className="flex items-center gap-2"><UserRoundCog size={17} aria-hidden="true"/>Change assigned manager</span><ChevronDown size={16} aria-hidden="true" className={assignmentOpen ? "rotate-180" : ""}/></Button>{assignmentOpen && <div id="reassignment-form" className="request-reassignment-form"><p className="text-sm text-muted">The new manager takes over this review. After reassignment, the request may leave your queue.</p><label className="block text-sm">Reassign to<select disabled={assignmentDisabled} aria-invalid={unavailableAssignee || undefined} aria-describedby={unavailableAssignee ? "reassignment-target-error" : undefined} className={`${fieldClass} mt-2`} value={assignmentTargetAvailable ? assignee : ""} onChange={e => setAssignee(e.target.value)}><option value="">Select manager</option>{otherManagers.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label><label className="block text-sm">Reason for reassignment<textarea disabled={mutation.isPending} className={`${fieldClass} mt-2`} maxLength={10000} value={assignmentReason} onChange={e => setAssignmentReason(e.target.value)}/></label><Button tone="secondary" disabled={!canReassign} onClick={() => { if (otherUnsentWork) setConfirmReassignment(true); else void reassign(); }}>Reassign</Button></div>}</section>}
        </section>
        {!showingAction && (mutation.error || downloadError) && <p ref={errorNotice} tabIndex={-1} role="alert" className="focus-ring rounded-xl border border-danger/30 bg-danger/10 p-4 text-sm text-danger">{mutation.error?.message || downloadError}</p>}
        <div className="request-activity-layout">
        <section aria-labelledby="request-comments-title" className="request-comments space-y-3 rounded-lg border border-line bg-panel p-4"><div className="flex items-center justify-between gap-2"><h3 id="request-comments-title" className="font-semibold">Comments</h3><span className="text-xs text-muted">{detail.data.comments.length}</span></div>
          {detail.data.comments.length === 0 && <p className="text-sm text-muted">{request.status === "draft" ? "Notes on this draft stay private until you submit it to your manager." : "No comments yet. Both participants can add relevant information."}</p>}
          {detail.data.comments.map(item => <div key={item.id} className="border-l-2 border-line pl-3"><p className="whitespace-pre-wrap text-sm">{item.body}</p><p className="mt-2 text-xs text-muted">{item.author} · {new Date(item.created_at).toLocaleString()}</p></div>)}
          <label className="block text-sm">Add comment<textarea disabled={mutation.isPending} className={`${fieldClass} mt-2 min-h-20`} maxLength={10000} value={comment} onChange={e => setComment(e.target.value)}/></label>
          {employee && request.status === "needs_information" && actions.includes("provide_information") && <p className="text-xs leading-5 text-muted">A general comment does not return the request to review. Use Reply to manager above to submit your answer.</p>}
          <Button tone="secondary" disabled={disabled || !comment.trim()} onClick={() => { clearSuccess(); void mutation.mutateAsync({ path: "comments", body: { body: comment } }).then(result => { setComment(""); showSuccess("Comment added to the request.", result); }).catch(() => {}); }}>Add comment</Button>
        </section>
        <section aria-labelledby="request-attachments-title" className="request-attachments space-y-3 rounded-lg border border-line bg-panel p-4"><div className="flex items-center justify-between gap-2"><h3 id="request-attachments-title" className="font-semibold">Attachments</h3><span className="text-xs text-muted">{detail.data.attachments.length} / 5</span></div><p className="text-xs leading-5 text-muted">PDF, PNG, JPEG or TXT · up to 5 MB. Visible only to participants and retained in the history.</p>
          {detail.data.attachments.length === 0 && <p className="text-sm text-muted">No attachments.</p>}
          {detail.data.attachments.map(item => <div key={item.id} className="rounded-xl border border-line p-3"><Button tone="ghost" disabled={disabled} onClick={() => { setDownloadError(""); void download(item.id, item.filename).catch(e => setDownloadError(e.message)); }}>{item.filename}</Button><p className="text-xs text-muted">{Math.ceil(item.size / 1024)} KB · {item.author} · {new Date(item.created_at).toLocaleString()}</p></div>)}
          {active && detail.data.attachments.length < 5 && <><label className="block text-sm">Choose attachment<input key={fileKey} type="file" disabled={mutation.isPending} accept=".pdf,.png,.jpg,.jpeg,.txt" aria-describedby={file ? "request-selected-attachment" : undefined} className={`${fieldClass} mt-2`} onChange={e => setFile(e.target.files?.[0] ?? null)}/></label>{file && <p id="request-selected-attachment" role="status" className="text-xs leading-5 text-muted [overflow-wrap:anywhere]">Selected file: {file.name}</p>}<Button tone="secondary" disabled={disabled || !file} onClick={() => { if (!file) return; clearSuccess(); const data = new FormData(); data.set("file", file); void mutation.mutateAsync({ path: "attachments", body: data }).then(() => { setFile(null); setFileKey(value => value + 1); }).catch(() => {}); }}>Upload attachment</Button></>}
        </section>
        </div>
        <RequestTimeline detail={detail.data}/>
        <details className="rounded-xl border border-line bg-panel p-4 text-sm text-muted"><summary className="focus-ring cursor-pointer font-semibold text-cream">Review procedure and privacy</summary><p className="mt-3 leading-6">{detail.data.procedure}</p></details>
      </div>}
    </RequestSurface>
    {request && selectedAction && <Drawer open={actionOpen} onOpenChange={value => { if (!value) closeAction(); }} title={`${actionLabel(action)} · ${requestNumber(request.number)}`} description={request.title}
      footer={confirm ? <div role="group" aria-label="Confirm action" className="space-y-3"><p className="text-sm">{action === "appeal" ? `Reopen ${requestNumber(request.number)} for the assigned manager? Its status will return to Submitted. The original decision and your reason stay in the history.` : `Record “${actionLabels[action]}” for ${requestNumber(request.number)}? This action and its reason remain in the history.`}</p><div className="form-actions"><Button tone="secondary" disabled={disabled} onClick={() => setConfirm(false)}>Go back</Button><Button tone={["reject", "cancel"].includes(action) ? "danger" : "primary"} disabled={disabled || !valid} onClick={() => void record()}>Confirm {actionLabels[action]}</Button></div></div>
        : <div className="form-actions"><Button tone="secondary" disabled={mutation.isPending} onClick={closeAction}>Back to request</Button><Button tone={["reject", "cancel"].includes(action) ? "danger" : "primary"} disabled={disabled || !valid} onClick={() => { if (["approve", "reject", "cancel", "complete", "appeal"].includes(action)) setConfirm(true); else void record(); }}>{mutation.isPending ? "Saving…" : submitLabel}</Button></div>}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm text-muted">{request.applicant}</span><Badge tone={statusTone(request.status)}>{requestLabel(request.status)}</Badge></div>
        {changedDuringReview && changeNotice}
        {detail.isError && <p role="alert" className="rounded-lg border border-danger/30 p-3 text-sm text-danger">The latest request could not be loaded. Return to the request and reload before continuing. Your notes are kept.</p>}
        {action === "appeal" && <><DecisionNote detail={detail.data!}/><p className="text-sm leading-6 text-muted">Explain what should be reconsidered and any relevant information the manager should review. This reopens the request for the same assigned manager; it does not guarantee a different decision. The original decision remains in the history.</p></>}
        {action === "provide_information" && <><p className="text-sm leading-6 text-muted">Your answer is saved in the history and returns the request for review.</p>{latestInformationRequest && <blockquote className="border-l-2 border-coral pl-3 text-sm leading-6">{String(latestInformationRequest.details.comment)}</blockquote>}</>}
        {user?.role === "manager" && <ReplyTemplates key={action} action={action} value={reason} disabled={mutation.isPending} onInsert={text => { setReason(text); setConfirm(false); setFair(false); }}/>}
        <label className="block text-sm font-medium">{reasonLabel}<textarea disabled={mutation.isPending} aria-required="true" aria-describedby={employee ? "request-action-help" : incompleteTemplate ? "request-template-help" : undefined} minLength={3} className={`${fieldClass} mt-2 min-h-28`} maxLength={10000} value={reason} onChange={event => { setReason(event.target.value); setConfirm(false); }}/></label>
        {incompleteTemplate && <p id="request-template-help" role="status" className="text-xs leading-5 text-coral">Replace every [[placeholder]] with request-specific information before continuing.</p>}
        {employee && <p id="request-action-help" className="text-xs leading-5 text-muted">Enter at least 3 characters. Include the facts your manager needs; avoid unrelated personal information.</p>}
        {decision && <><label className="block text-sm font-medium">Relevant policy or objective criteria *<textarea disabled={mutation.isPending} aria-required="true" minLength={3} className={`${fieldClass} mt-2 min-h-24`} maxLength={10000} value={basis} onChange={event => { setBasis(event.target.value); setConfirm(false); }}/></label><label className="flex items-start gap-3 text-sm leading-6"><input disabled={mutation.isPending} type="checkbox" className="focus-ring mt-1 h-5 w-5 shrink-0" checked={fair} onChange={event => { setFair(event.target.checked); setConfirm(false); }}/>I applied the same relevant criteria as for other employees. This decision does not rely on protected or unrelated personal characteristics.</label></>}
        {mutation.error && <p ref={errorNotice} tabIndex={-1} role="alert" className="focus-ring rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">{mutation.error.message}</p>}
        <p className="text-xs leading-5 text-muted">Both participants can read your explanation in the request history. Include only relevant information.</p>
      </div>
    </Drawer>}
    <Drawer open={discardAction} onOpenChange={setDiscardAction} title={employee ? "Discard unsent text?" : "Discard review notes?"} description="Only the unsent text for this action will be removed. The saved request, comments and history stay unchanged." placement="center" size="small" children={null} footer={<div className="form-actions"><Button tone="secondary" onClick={() => setDiscardAction(false)}>Keep notes</Button><Button tone="danger" onClick={() => { setDiscardAction(false); setAction(""); setActionOpen(false); setReason(""); setBasis(""); setFair(false); setConfirm(false); }}>Discard notes</Button></div>}/>
    {editing && request && <RequestDrawer open={editing} initial={request} onOpenChange={setEditing} onOpenRequest={() => setEditing(false)}/>}
    <Drawer open={discardOpen} onOpenChange={setDiscardOpen} title="Leave without sending?" description="Your unsent text and selected attachment will be discarded. Saved request data will stay unchanged." placement="center" size="small" children={null} footer={<div className="form-actions"><Button tone="secondary" onClick={() => setDiscardOpen(false)}>Continue editing</Button><Button tone="danger" onClick={() => { clearUnsavedChanges(); setDiscardOpen(false); onClose(); }}>Discard unsent changes</Button></div>}/>
    <Drawer open={confirmReassignment} onOpenChange={value => { if (!mutation.isPending) setConfirmReassignment(value); }} title="Reassign with unsent changes?" description="Reassigning closes this request for you. Your unsent comment, review text or selected attachment will not be saved. The reassignment reason will be recorded." placement="center" size="small" children={null} footer={<div className="form-actions"><Button tone="secondary" disabled={mutation.isPending} onClick={() => setConfirmReassignment(false)}>Keep editing</Button><Button tone="danger" disabled={!canReassign} onClick={() => void reassign()}>Reassign and discard unsent changes</Button></div>}/>
  </>;
}

function RequestSurface({ open, onClose, presentation, title, children }: { open: boolean; onClose: () => void; presentation: "dialog" | "page"; title: string; children: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (open && presentation === "page") { heading.current?.focus({ preventScroll: true }); if (!window.matchMedia?.("(min-width: 1280px)").matches) window.scrollTo?.({ top: 0 }); } }, [open, presentation]);
  if (presentation === "dialog") return <Drawer open={open} onOpenChange={value => { if (!value) onClose(); }} title={title} description="Details, decisions and a complete history of this request." placement="center" size="large">{children}</Drawer>;
  if (!open) return null;
  return <section className="request-detail-page mx-auto max-w-5xl"><Button tone="ghost" className="request-back-button" onClick={onClose}><ArrowLeft size={16} aria-hidden="true"/>Back to requests</Button><h2 ref={heading} tabIndex={-1} className="mb-2 break-words text-xl font-semibold outline-none">{title}</h2>{children}</section>;
}
