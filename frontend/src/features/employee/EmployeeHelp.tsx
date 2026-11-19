import { ClipboardList, MessageSquare } from "lucide-react";
import { useLocation, useNavigate } from "react-router";
import { Button, Drawer } from "../../components/ui";
import { useProtectedNavigation } from "../../components/UnsavedChanges";

export function EmployeeHelp({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const protect = useProtectedNavigation();
  const go = (path: string) => {
    // Returning to a chat already open should keep its conversation and draft.
    if (path === "/employee" && location.pathname === "/employee") { onOpenChange(false); return; }
    protect(() => { onOpenChange(false); navigate(path); });
  };

  return <Drawer open={open} onOpenChange={onOpenChange} title="Getting help" description="Choose the right place for your next step." placement="center" size="medium"
    footer={<Button tone="secondary" onClick={() => onOpenChange(false)}>Close help</Button>}>
    <div className="space-y-5">
      <section aria-labelledby="employee-help-chat" className="rounded-lg border border-line p-4">
        <h2 id="employee-help-chat" className="flex items-center gap-2 text-base font-semibold"><MessageSquare size={18} className="shrink-0 text-muted" aria-hidden="true"/>Ask a question</h2>
        <p className="mt-2 text-sm leading-6 text-muted">Use My chats for company policies, benefits and everyday work questions. Ask in English and check the sources provided with an answer. Saved conversations can be reopened and continued.</p>
        <Button tone="secondary" className="mt-3" onClick={() => go("/employee")}>Open my chats</Button>
      </section>
      <section aria-labelledby="employee-help-request" className="rounded-lg border border-line p-4">
        <h2 id="employee-help-request" className="flex items-center gap-2 text-base font-semibold"><ClipboardList size={18} className="shrink-0 text-muted" aria-hidden="true"/>Request action or approval</h2>
        <p className="mt-2 text-sm leading-6 text-muted">Create a request for time off, a document or another available category. You can save a private draft before submitting it to the assigned manager.</p>
        <div className="mt-3 flex flex-wrap gap-2"><Button onClick={() => go("/requests?new=1")}>Create a request</Button><Button tone="secondary" onClick={() => go("/requests")}>Open my requests</Button></div>
      </section>
      <section aria-labelledby="employee-help-follow-up">
        <h2 id="employee-help-follow-up" className="text-sm font-semibold">Follow up on a request</h2>
        <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-6 text-muted">
          <li>Open My requests to see the current status, decision reason and complete history.</li>
          <li>If more information is needed, open the request and use Reply to manager.</li>
          <li>To challenge a decision, open the request and use Request reconsideration when it is available. The original decision stays in its history.</li>
        </ul>
      </section>
      <section aria-labelledby="employee-help-notifications" className="border-t border-line pt-4">
        <h2 id="employee-help-notifications" className="text-sm font-semibold">Private notifications</h2>
        <p className="mt-2 text-sm leading-6 text-muted">Connect your own Slack or Discord account in Personal notifications. Requests for additional information can arrive privately. Approval, rejection and other status changes are not sent automatically; check My requests for the latest status.</p>
      </section>
    </div>
  </Drawer>;
}
