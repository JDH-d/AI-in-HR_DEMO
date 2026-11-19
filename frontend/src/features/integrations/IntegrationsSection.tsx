import { Check, MessageCircle, ShieldCheck, Users } from "lucide-react";
import { Badge, Button, Card, LoadingSkeleton } from "../../components/ui";
import { useIntegrations } from "./useIntegrations";
import "./integrations.css";

export function IntegrationsSection() {
  const { query, toggle, test } = useIntegrations();
  if (query.isLoading) return <LoadingSkeleton label="Loading integrations…"/>;
  if (query.isError) return <Card><p role="alert">Unable to load integrations.</p><p className="mt-1 text-sm text-muted">Try loading the connections again.</p><Button tone="secondary" onClick={() => void query.refetch()}>Retry</Button></Card>;
  return <div className="integration-workspace">
    <section className="integration-intro" aria-labelledby="notification-overview-title">
      <ShieldCheck size={20} aria-hidden="true" className="shrink-0 text-lime"/>
      <div><h2 id="notification-overview-title" className="font-semibold">Request notifications</h2><p className="text-sm text-muted">Private delivery to connected accounts. Each service is controlled separately.</p></div>
      <details className="integration-policy"><summary className="focus-ring">Who receives which messages?</summary><div>
        <p>Managers receive work for their assigned requests. Employees receive requests for additional information, without automatic approval or rejection messages.</p>
        <p>Personal employee chats are not forwarded. Request links require the appropriate account permissions.</p>
        <p className="[overflow-wrap:anywhere]">Application link: {query.data?.app_url || "Not configured"}</p>
      </div></details>
    </section>
    <div className="integration-services">{query.data?.items.map(item => {
      const name = item.provider === "slack" ? "Slack" : "Discord";
      const delivery = item.active_delivery ?? item.last_delivery;
      const busy = toggle.isPending || test.isPending;
      return <section key={item.provider} className="integration-service" aria-labelledby={`${item.provider}-service-title`}>
        <header className="integration-service-header">
          <span className="integration-service-icon"><MessageCircle size={21} aria-hidden="true"/></span>
          <div className="integration-service-heading"><div className="integration-name-line"><h2 id={`${item.provider}-service-title`}>{name}</h2><Badge tone={item.enabled && item.configured ? "success" : "neutral"}>{item.enabled ? (item.configured ? "Enabled" : "Needs configuration") : "Disabled"}</Badge></div>
            <p>{item.configured ? item.enabled ? "Personal delivery is on." : "Ready to enable personal delivery." : "Server setup is required before personal delivery can start."}</p>
          </div>
          <Button tone="secondary" role="switch" aria-checked={item.enabled} aria-label={`Enable ${name} notifications`} disabled={busy || (!item.enabled && !item.configured)} onClick={() => { test.reset(); toggle.mutate(item); }}>{item.enabled ? "Disable" : "Enable"}</Button>
        </header>
        <div className="integration-service-body">
          <div className="integration-recipients" aria-label={`${name} recipients`}>
            <h3><Users size={16} aria-hidden="true"/>Recipients</h3>
            {(["employee", "manager"] as const).map(audience => {
              const label = audience === "employee" ? "Employee" : "Manager";
              const why = !item.configured ? "Complete server setup to test delivery." : !item.recipients?.[audience] ? `Connect the ${label} account in Personal notifications.` : !item.enabled ? "Enable personal delivery to send a test." : "Send a test only to this account.";
              return <div key={audience} className="integration-recipient-row">
                <div><p className="font-medium">{label}</p><p className="integration-recipient-state">{item.recipients?.[audience] ? <><Check size={13} aria-hidden="true"/>Connected</> : "Not connected"}</p></div>
                <Button tone="secondary" aria-label={`Send ${name} test to ${label}`} aria-describedby={`${item.provider}-${audience}-test-help`} disabled={busy || !item.enabled || !item.configured || !item.recipients?.[audience]} onClick={() => { toggle.reset(); test.mutate({provider: item.provider, audience}); }}>Send test</Button>
                <p id={`${item.provider}-${audience}-test-help`} className={item.configured && !item.recipients?.[audience] ? "integration-recipient-help" : "sr-only"}>{why}</p>
              </div>;
            })}
            <p className="integration-footnote">Tests go only to the selected account. They do not change requests.</p>
          </div>
          <div className="integration-service-details">
            {!item.configured && <details className="integration-disclosure"><summary className="focus-ring">Setup instructions</summary><div><p className="[overflow-wrap:anywhere]">{item.configuration_error}</p><p>Follow the bot setup instructions in the project README. Channel webhooks do not provide personal delivery.</p></div></details>}
            <details open={Boolean(delivery?.error || item.pending)} className="integration-disclosure"><summary className="focus-ring">Delivery activity · {delivery ? delivery.status : "No notifications yet"}</summary><div aria-live="polite">
              <p>Queued or sending: {item.pending}</p>
              {delivery ? <><p>{item.active_delivery ? "Current notification" : "Last notification"}: {delivery.status} · Attempts: {delivery.attempts}</p><p className="text-xs text-muted">{new Date(delivery.updated_at * 1000).toLocaleString()}</p>{delivery.error && <p className="text-danger">{delivery.error}</p>}{delivery.status === "pending" && delivery.attempts > 0 && <p className="text-xs text-muted">Retry no earlier than {new Date(delivery.next_attempt_at * 1000).toLocaleString()}.</p>}</> : <p className="text-muted">No notifications yet.</p>}
            </div></details>
            <details className="integration-disclosure"><summary className="focus-ring">Delivery rules</summary><div><p>Changes apply immediately. Enabling starts with future events. Disabling cancels queued notifications; a delivery already in progress may finish.</p><p>Credentials stay on the server and are never displayed here.</p></div></details>
          </div>
        </div>
        {toggle.isError && toggle.variables?.provider === item.provider && <p role="alert" className="integration-result text-danger">{toggle.error.message}</p>}
        {test.isError && test.variables?.provider === item.provider && <p role="alert" className="integration-result text-danger">{test.error.message}</p>}
        {test.isSuccess && test.variables?.provider === item.provider && <p role="status" className="integration-result success-feedback">Test notification accepted for {test.variables.audience === "employee" ? "Employee" : "Manager"}. Check delivery activity for the result.</p>}
      </section>;
    })}</div>
  </div>;
}
