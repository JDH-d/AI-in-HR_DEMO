import { Bell, MessageCircle, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../../app/providers";
import { ActionBar, Badge, Button, Drawer, LoadingSkeleton, fieldClass } from "../../components/ui";
import { providerName, usePersonalNotifications } from "./usePersonalNotifications";
import "./integrations.css";

export function PersonalNotifications({open: controlledOpen, onOpenChange, hideTrigger = false}: {open?: boolean; onOpenChange?: (value: boolean) => void; hideTrigger?: boolean}) {
  const { user } = useAuth();
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = onOpenChange ?? setLocalOpen;
  if (user?.role !== "employee" && user?.role !== "manager") return null;
  return <>
    {!hideTrigger && <Button tone="ghost" className="w-full justify-start" onClick={() => setOpen(true)} aria-haspopup="dialog">
      <Bell size={16}/>Personal notifications
    </Button>}
    <Drawer open={open} onOpenChange={setOpen} title="Personal notifications" description="Connect your accounts for private messages from PeopleFlow.">
      {open && <PersonalNotificationSettings key={user.id}/>}
    </Drawer>
  </>;
}

function PersonalNotificationSettings() {
  const {user, query, codes, disconnect, setDisconnect, notice, action, run} = usePersonalNotifications();
  if (query.isLoading) return <LoadingSkeleton label="Loading personal connections…" rows={2}/>;
  if (query.isError) return <div role="alert">Unable to load your connections. Try again.<Button tone="secondary" onClick={() => void query.refetch()}>Retry connections</Button></div>;
  return <div className="personal-connections">
    <div className="personal-connections-toolbar"><p>Signed in as {user?.display_name} ({user?.role}).</p>
      <Button tone="ghost" aria-label="Refresh connections" disabled={query.isFetching || action.isPending} onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true"/>Refresh</Button>
    </div>
    <details className="personal-message-policy"><summary className="focus-ring">{user?.role === "employee" ? "Messages about your own requests" : "Messages for your assigned work"}</summary>
      <p>{user?.role === "employee"
        ? "You receive requests for additional information about your own requests. Approval, rejection and other status changes are not sent automatically."
        : "You receive request work addressed to you, including new submissions and employee replies. Personal employee chat conversations are not forwarded."}</p>
    </details>
    {notice && <p role="status" className="personal-connection-notice">{notice}</p>}
    <div className="personal-connection-list">{query.data?.items.map(item => {
      const name = providerName(item.provider);
      const code = codes[item.provider];
      const busy = action.isPending;
      const storedConnection = item.connected || Boolean(item.external_user_id);
      const needsReconnect = storedConnection && !item.connected;
      const linking = item.configured && !storedConnection && Boolean(code || item.pending);
      return <section key={item.provider} className="personal-connection" aria-labelledby={`${item.provider}-personal-title`}>
        <header className="personal-connection-header"><span className="integration-service-icon"><MessageCircle size={20} aria-hidden="true"/></span><h2 id={`${item.provider}-personal-title`}>{name}</h2><Badge tone={item.connected ? "success" : needsReconnect ? "warning" : "neutral"}>{item.connected ? "Connected" : needsReconnect ? "Reconnect needed" : item.pending ? "Awaiting your confirmation" : "Not connected"}</Badge></header>
        {!item.configured && <p className="personal-connection-help">The {name} bot is not configured. Ask the demo administrator to complete its server setup.</p>}
        {item.configured && !item.enabled && <p className="personal-connection-help">{name} delivery is disabled by the administrator. You can connect your account now; messages start after delivery is enabled.</p>}
        {item.configured && item.enabled && !storedConnection && !linking && <p className="personal-connection-help">Get a private code, link it in the bot, then confirm your account here.</p>}
        {storedConnection && <p className="personal-account-id">{item.connected ? "Connected" : "Previously connected"} account ID: {item.external_user_id}</p>}
        {needsReconnect && <p role="alert" className="personal-connection-help text-coral">{item.connection_error || "This connection no longer matches the configured bot. Disconnect and connect again."}</p>}
        {linking && <ol aria-label={`${name} connection steps`} className="personal-link-steps">
          {["Get a code", "Link in bot", "Confirm account"].map((step, index) => {
            const current = item.pending ? 2 : code ? 1 : 0;
            return <li key={step} aria-current={current === index ? "step" : undefined}><span aria-hidden="true">{index + 1}</span>{step}</li>;
          })}
        </ol>}
        {item.pending && <div className="personal-confirmation">
          <p>{name} account ID <strong>{item.pending.external_user_id}</strong> used your connection code. Verify that this is your own account before confirming.</p>
          <Button disabled={busy} onClick={() => run({ provider: item.provider, kind: "confirm", challengeId: item.pending!.challenge_id })}>Confirm my {name} account</Button>
        </div>}
        {code && !item.pending && !storedConnection && <div className="personal-link-command">
          <label htmlFor={`${item.provider}-connection-command`}>Run in a private conversation with the {name} bot</label>
          <textarea id={`${item.provider}-connection-command`} readOnly aria-label={`${name} connection command`} className={`${fieldClass} min-h-24 resize-y`} value={code.command}/>
          <p>Keep this single-use code private. It expires at {new Date(code.expires_at * 1000).toLocaleTimeString()}.</p>
          <Button tone="secondary" disabled={query.isFetching || busy} onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true"/>I linked it — refresh</Button>
          <p>Return here, refresh connections, and confirm the account shown above.</p>
        </div>}
        <div className="personal-connection-actions"><ActionBar label={`${name} connection actions`}>
          {!storedConnection && <Button tone={code || item.pending ? "secondary" : "primary"} disabled={busy || !item.configured} onClick={() => run({ provider: item.provider, kind: "code" })}>{code || item.pending ? `Generate new ${name} code` : `Connect ${name}`}</Button>}
          {item.connected && <Button tone="secondary" disabled={busy || !item.configured || !item.enabled} onClick={() => run({ provider: item.provider, kind: "test" })}>Send {name} test to me</Button>}
          {(storedConnection || item.pending) && disconnect !== item.provider && <Button tone="ghost" disabled={busy} onClick={() => setDisconnect(item.provider)}>Disconnect {name}</Button>}
        </ActionBar></div>
        {disconnect === item.provider && <div className="personal-disconnect-confirmation">
          <p>Disconnect {name}? Personal notifications stop for this account. Your requests and chats remain saved.</p>
          <div className="flex flex-wrap gap-2"><Button tone="secondary" disabled={busy} onClick={() => setDisconnect(null)}>Keep connection</Button><Button tone="danger" disabled={busy} onClick={() => run({ provider: item.provider, kind: "disconnect" })}>Confirm disconnect {name}</Button></div>
        </div>}
        {action.isError && action.variables.provider === item.provider && <p role="alert" className="personal-connection-help text-danger">{action.error.message} Refresh connections and try again.</p>}
      </section>;
    })}</div>
    <details className="personal-message-policy"><summary className="focus-ring">About account linking</summary><p>Connecting an account does not change your role. Use separate Slack or Discord accounts for the Employee and Manager demo users.</p></details>
  </div>;
}
