import { RefreshCw } from "lucide-react";
import { Button, Drawer } from "../../components/ui";
import type { BulkReviewState } from "./useManagerWorkspace";

const numberLabel = (number: number) => `REQ-${String(number).padStart(6, "0")}`;
export function ManagerBulkReview({ state, disabled, onReload, onOpenRequest, onReviewQueue }: { state: BulkReviewState; disabled: boolean; onReload: () => void; onOpenRequest: (id: string) => void; onReviewQueue?: () => void }) {
  const { selecting, selected, eligible, confirm, setConfirm, mutation, outcome } = state;
  const started = outcome?.result.results.filter(item => item.success) ?? [];
  const notChanged = outcome?.result.results.filter(item => !item.success) ?? [];
  const successes = started.length;
  return <section aria-label="Bulk review" className="manager-bulk">
    {!selecting ? <div className="manager-bulk-toolbar"><Button tone="secondary" disabled={disabled || mutation.isPending || !eligible.length} onClick={() => state.setSelecting(true)}>Select requests</Button><Button tone="ghost" disabled={mutation.isPending} onClick={onReload} aria-label="Refresh queue"><RefreshCw size={16} aria-hidden="true"/></Button><p>Only new requests can be started together. Decisions are reviewed individually.</p></div> : <div className="manager-bulk-toolbar">
      <label className="manager-selection-label"><input type="checkbox" className="focus-ring" checked={eligible.length > 0 && selected.length === eligible.length} disabled={disabled || mutation.isPending || !eligible.length} onChange={state.selectAll}/>Select new requests on this page</label>
      <span role="status">{selected.length} selected</span>
      <Button disabled={disabled || mutation.isPending || !selected.length} onClick={() => setConfirm(true)}>Start review ({selected.length})</Button>
      <Button tone="ghost" disabled={mutation.isPending} onClick={state.clear}>Cancel selection</Button>
    </div>}
    {state.notice && <div role="alert" className="manager-inline-error"><p>{state.notice}</p><Button tone="secondary" disabled={mutation.isPending} onClick={onReload}>Reload queue</Button></div>}
    {outcome && <div className={`manager-bulk-result${successes > 0 ? " success-feedback" : ""}`} role="status">
      <p>{successes} started · {notChanged.length} not changed.</p>
      {successes > 0 && <details open={notChanged.length > 0} className="mt-2"><summary className="focus-ring rounded">Started requests ({successes})</summary><ul aria-label="Started requests" className="mt-1 space-y-1">{started.map(item => {
        const request = outcome.items.find(selectedItem => selectedItem.id === item.id);
        return <li key={item.id}><strong>{request ? numberLabel(request.number) : item.id}</strong>{request && ` · ${request.title}`}</li>;
      })}</ul></details>}
      {notChanged.length > 0 && <div className="mt-2"><p className="font-semibold">Not changed</p><ul aria-label="Requests not changed" className="space-y-1">{notChanged.map(item => <li key={item.id}>{numberLabel(outcome.items.find(request => request.id === item.id)?.number ?? 0)}: {item.error || "Review the current request and try again."}</li>)}</ul></div>}
      {successes > 0 && onReviewQueue && <Button tone="ghost" onClick={onReviewQueue}>View in-review queue</Button>}
      {successes === 1 && <Button tone="ghost" onClick={() => onOpenRequest(started[0].id)}>Open started request</Button>}
    </div>}
    <Drawer open={confirm} onOpenChange={value => { if (!mutation.isPending) setConfirm(value); }} title={`Start review of ${selected.length} requests?`} description="This moves only the selected new requests to In review. It does not approve, reject or reassign them. Each request is checked again before changing it." placement="center" size="medium" footer={<div className="form-actions"><Button tone="secondary" disabled={mutation.isPending} onClick={() => setConfirm(false)}>Keep selecting</Button><Button disabled={disabled || mutation.isPending || !selected.length} onClick={state.start}>{mutation.isPending ? "Starting reviews…" : "Start selected reviews"}</Button></div>}>
      <ul className="manager-bulk-preview">{selected.map(item => <li key={item.id}><strong>{numberLabel(item.number)}</strong> {item.title}</li>)}</ul>
    </Drawer>
  </section>;
}
