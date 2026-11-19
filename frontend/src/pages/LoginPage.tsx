import { ArrowRight, BrainCircuit, BriefcaseBusiness, Check, LibraryBig, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Navigate, useLocation } from "react-router";
import type { Role } from "../api/types";
import { Button, Card, fieldClass } from "../components/ui";
import { ThemeControl } from "../components/ThemeControl";
import { useAuth } from "../app/providers";
import { ApiError } from "../api/client";

const roles = [
  {id: "employee" as Role, title: "Employee", copy: "See your tasks, manage requests and find help.", icon: BrainCircuit, path: "/home"},
  {id: "manager" as Role, title: "Manager", copy: "Review the requests assigned to you.", icon: BriefcaseBusiness, path: "/manager"},
  {id: "knowledge_admin" as Role, title: "Knowledge Admin", copy: "Manage documents, answer quality and settings.", icon: LibraryBig, path: "/knowledge"},
];
type SignInError = { message: string; field: "username" | "password" | "credentials" | "connection" };
export function LoginPage() {
  const { user, login } = useAuth();
  const location = useLocation();
  const destination = (role: Role) => {
    const target = location.state?.returnTo;
    if (role === "employee" && typeof target === "string" && /^\/employee(?:\?|$)/.test(target)) return target;
    return role !== "knowledge_admin" && typeof target === "string" && /^\/requests(?:\?|$)/.test(target)
      ? target : roles.find(item => item.id === role)!.path;
  };
  const [username, setUsername] = useState("employee");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<SignInError | null>(null);
  const [busy, setBusy] = useState(false);
  const usernameField = useRef<HTMLInputElement>(null);
  const passwordField = useRef<HTMLInputElement>(null);
  const normalizedUsername = username.trim().toLowerCase();
  const activeRole = roles.find(role => role.id === normalizedUsername);
  const usernameInvalid = error?.field === "username" || error?.field === "credentials";
  const passwordInvalid = error?.field === "password" || error?.field === "credentials";
  useEffect(() => { document.title = "Sign in · PeopleFlow AI"; }, []);
  useEffect(() => {
    if (error && !busy) (error.field === "username" || error.field === "credentials" ? usernameField : passwordField).current?.focus();
  }, [error, busy]);
  if (user) return <Navigate to={destination(user.role)} replace />;
  const submit = async () => {
    if (busy) return;
    if (!normalizedUsername) { setError({message: "Enter your demo username or choose a workspace to continue.", field: "username"}); return; }
    if (!password) { setError({message: "Enter the demo password to continue.", field: "password"}); return; }
    setBusy(true);
    setError(null);
    // The authenticated user returned by the server drives the Navigate above.
    try { await login(normalizedUsername, password); }
    catch (e) {
      setError(e instanceof ApiError && [401, 403, 422].includes(e.status)
        ? {message: "That username or password wasn't accepted. Check your demo username and password, then try again.", field: "credentials"}
        : e instanceof ApiError && e.status === 429
          ? {message: "Too many sign-in attempts. Wait one minute, then try again.", field: "connection"}
          : {message: "Unable to reach your workspace. Check that the application is running, then try again.", field: "connection"});
    }
    finally { setBusy(false); }
  };
  return <main className="login-page">
    <header className="login-header">
      <div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-lg bg-accent text-on-accent"><ShieldCheck size={22}/></span><strong>PeopleFlow AI</strong></div>
      <div className="login-theme"><ThemeControl compact/></div>
    </header>
    <div className="login-content">
      <div className="mb-5"><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Sign in to your workspace</h1><p className="mt-2 text-sm leading-6 text-muted">Choose a demo account or enter its username.</p></div>
      <Card padding="none" className="overflow-hidden">
        <form noValidate onSubmit={event => { event.preventDefault(); void submit(); }}>
          <fieldset disabled={busy} className="login-layout"><legend className="sr-only">Demo account</legend>
            <div className="login-workspaces"><p className="mb-3 text-sm font-semibold">1. Choose your workspace</p>
              <div className="login-role-list">{roles.map(({ id, title, copy, icon: Icon }) => <button key={id} type="button" aria-pressed={activeRole?.id === id} onClick={() => { setUsername(id); setError(null); }}
                className={`login-role focus-ring ${activeRole?.id === id ? "border-lime bg-lime-soft" : "border-line hover:bg-raised"}`}>
                <Icon size={20} className="shrink-0 text-lime" aria-hidden="true"/><span className="min-w-0 flex-1"><strong className="block text-sm">{title}</strong><span className="login-role-description">{copy}</span></span>
                {activeRole?.id === id && <Check size={16} className="login-role-check shrink-0 text-lime" aria-hidden="true"/>}
              </button>)}</div>
            </div>
            <div className="login-credentials">
            <p className="text-sm font-semibold">2. Enter your username and password</p>
            <h2 className="mt-4 text-xl font-semibold">{activeRole ? `Sign in as ${activeRole.title}` : "Sign in"}</h2>
            <p className="mb-5 mt-1 text-sm leading-6 text-muted">{activeRole?.copy ?? "Use your demo account to open its workspace."}</p>
            <label htmlFor="demo-username" className="mb-2 block text-sm font-medium">Username</label>
            <input ref={usernameField} id="demo-username" name="username" className={fieldClass} type="text" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} required maxLength={80} value={username}
              aria-invalid={usernameInvalid} aria-describedby={usernameInvalid ? "username-help sign-in-error" : "username-help"} onChange={event => { setUsername(event.target.value); setError(null); }}/>
            <p id="username-help" className="mb-4 mt-2 text-xs leading-5 text-muted">Choose a workspace to fill in its demo username, or type it here.</p>
            <label htmlFor="demo-password" className="mb-2 block text-sm font-medium">Demo password</label>
            <input ref={passwordField} id="demo-password" name="password" className={fieldClass} type="password" autoComplete="current-password" required maxLength={1024} value={password}
              aria-invalid={passwordInvalid} aria-describedby={passwordInvalid ? "password-help sign-in-error" : "password-help"} onChange={event => { setPassword(event.target.value); setError(null); }}/>
            <p id="password-help" className="mt-2 text-xs text-muted">Use the password configured for this demo.</p>
            {error && <p id="sign-in-error" role="alert" className="mt-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm text-danger">{error.message}</p>}
            <Button type="submit" className="mt-4 w-full" disabled={busy}>{busy ? "Opening workspace…" : "Continue"}<ArrowRight size={16}/></Button>
            </div>
          </fieldset>
        </form>
      </Card>
      <p className="mt-4 text-center text-xs leading-5 text-muted">Each account has its own permissions. Chats and requests stay saved.</p>
    </div>
  </main>;
}
