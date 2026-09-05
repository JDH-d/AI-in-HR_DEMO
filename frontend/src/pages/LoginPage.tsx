import {
  ArrowRight,
  Books,
  Briefcase,
  Check,
  Eye,
  EyeSlash,
  type Icon,
  User,
} from "@phosphor-icons/react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import type { Role } from "../api/types";
import { useAuth } from "../app/providers";
import { BrandMark } from "../components/BrandMark";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button, Card, fieldClass } from "../components/ui";

const roles = [
  {
    id: "employee",
    title: "Employee",
    copy: "Ask questions and manage your requests",
    icon: User,
    path: "/employee",
  },
  {
    id: "manager",
    title: "Manager",
    copy: "Review and respond to team requests",
    icon: Briefcase,
    path: "/manager",
  },
  {
    id: "knowledge_admin",
    title: "Knowledge Admin",
    copy: "Manage documents and assistant settings",
    icon: Books,
    path: "/knowledge",
  },
] satisfies ReadonlyArray<{
  id: Role;
  title: string;
  copy: string;
  icon: Icon;
  path: string;
}>;

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Role>("employee");
  const [password, setPassword] = useState("demo-password");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await login(selected, password);
      const destination = roles.find((role) => role.id === selected)?.path ?? "/";
      navigate(destination);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col bg-ink text-cream">
      <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-line px-5 sm:px-8">
        <div className="flex items-center gap-3">
          <BrandMark size={27} />
          <span className="text-[15px] font-semibold tracking-[-.02em]">PeopleFlow AI</span>
          <span className="hidden border-l border-line pl-3 text-sm text-muted sm:block">
            HR assistant
          </span>
        </div>
        <ThemeToggle />
      </header>

      <div className="flex flex-1 items-center justify-center px-5 py-10 sm:py-14">
        <div className="w-full max-w-[460px]">
          <div className="mb-6">
            <h1 className="text-2xl font-semibold leading-8 tracking-[-.025em]">
              Open your workspace
            </h1>
            <p className="mt-2 text-sm leading-6 text-muted">Choose a demo account to continue.</p>
          </div>

          <Card className="p-5 sm:p-6">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
              aria-busy={busy}
            >
              <fieldset disabled={busy}>
                <legend className="mb-3 text-sm font-medium">Demo account</legend>
                <div className="space-y-2">
                  {roles.map(({ id, title, copy, icon: RoleIcon }) => (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={selected === id}
                      onClick={() => setSelected(id)}
                      className={`focus-ring flex w-full items-center gap-3 rounded-lg border px-3.5 py-3 text-left transition-colors disabled:cursor-wait ${selected === id ? "border-accent/50 bg-accent-soft" : "border-line bg-panel hover:bg-raised"}`}
                    >
                      <RoleIcon
                        size={21}
                        weight="regular"
                        className={`shrink-0 ${selected === id ? "text-accent" : "text-muted"}`}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium leading-5">{title}</span>
                        <span className="mt-0.5 block text-xs leading-[18px] text-muted">
                          {copy}
                        </span>
                      </span>
                      <span
                        aria-hidden="true"
                        className={`grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border ${selected === id ? "border-accent bg-accent text-on-accent" : "border-line"}`}
                      >
                        {selected === id && <Check size={12} weight="bold" />}
                      </span>
                    </button>
                  ))}
                </div>
              </fieldset>

              <div className="mt-5 border-t border-line pt-5">
                <label htmlFor="demo-password" className="mb-2 block text-sm font-medium">
                  Demo password
                </label>
                <div className="relative">
                  <input
                    id="demo-password"
                    className={`${fieldClass} pr-12`}
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    aria-describedby="demo-password-help"
                    value={password}
                    disabled={busy}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((value) => !value)}
                    className="focus-ring absolute inset-y-1 right-1 flex w-10 items-center justify-center rounded-md text-muted transition-colors hover:bg-raised hover:text-cream"
                  >
                    {showPassword ? <EyeSlash size={19} /> : <Eye size={19} />}
                  </button>
                </div>
                <p id="demo-password-help" className="mt-2 text-xs leading-5 text-muted">
                  The password is prefilled for all demo accounts.
                </p>
                {error && (
                  <p role="alert" className="mt-3 text-sm leading-5 text-danger">
                    {error}
                  </p>
                )}
                <Button className="mt-5 w-full" type="submit" disabled={busy}>
                  {busy ? "Opening workspace…" : "Continue"}
                  {!busy && <ArrowRight size={17} aria-hidden="true" />}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      </div>
    </main>
  );
}
