import { ArrowRight, BrainCircuit, BriefcaseBusiness, LibraryBig, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import type { Role } from "../api/types";
import { Button, Card, fieldClass } from "../components/ui";
import { useAuth } from "../app/providers";

const roles = [
  { id: "employee" as Role, title: "Employee", copy: "Ask, act, and track without chasing a portal.", icon: BrainCircuit, path: "/employee" },
  { id: "manager" as Role, title: "Manager", copy: "Review decisions with context and an audit trail.", icon: BriefcaseBusiness, path: "/manager" },
  { id: "knowledge_admin" as Role, title: "Knowledge Admin", copy: "Keep answers grounded, current, and measurable.", icon: LibraryBig, path: "/knowledge" },
];
export function LoginPage() {
  const { user, login } = useAuth(); const navigate = useNavigate();
  const [selected, setSelected] = useState<Role>("employee"); const [password, setPassword] = useState("demo-password");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;
  const submit = async () => { setBusy(true); setError(""); try { await login(selected, password); navigate(roles.find(r=>r.id===selected)!.path); } catch (e) { setError(e instanceof Error ? e.message : "Login failed"); } finally { setBusy(false); } };
  return <main className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-5 py-12">
    <div className="mb-10 flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-2xl bg-lime text-ink"><ShieldCheck size={22}/></div><div><div className="font-semibold">PeopleFlow AI</div><div className="text-xs text-muted">Employee operations, with evidence</div></div></div>
    <div className="grid gap-10 lg:grid-cols-[1.05fr_.95fr]"><section><span className="text-xs font-bold uppercase tracking-[.2em] text-lime">Choose your workspace</span><h1 className="mt-5 max-w-2xl text-5xl font-medium leading-[1.02] tracking-[-.045em] sm:text-7xl">Work questions become <span className="text-coral">clear next steps.</span></h1><p className="mt-6 max-w-xl text-lg leading-8 text-muted">A grounded AI workspace for people, decisions, and the knowledge behind them.</p></section>
    <Card className="soft-shadow p-3"><div className="space-y-2">{roles.map(({id,title,copy,icon:Icon})=><button key={id} onClick={()=>setSelected(id)} className={`focus-ring flex w-full items-center gap-4 rounded-xl border p-4 text-left transition ${selected===id?"border-lime/50 bg-lime-soft":"border-transparent hover:bg-raised"}`}><span className={`grid h-11 w-11 place-items-center rounded-xl ${selected===id?"bg-lime text-ink":"bg-raised text-muted"}`}><Icon size={20}/></span><span className="flex-1"><strong className="block text-sm">{title}</strong><span className="mt-1 block text-xs leading-5 text-muted">{copy}</span></span><ArrowRight size={17} className={selected===id?"text-lime":"text-muted"}/></button>)}</div>
    <div className="mt-4 border-t border-line p-4"><label className="mb-2 block text-xs font-semibold text-muted">Demo password</label><input className={fieldClass} type="password" value={password} onChange={e=>setPassword(e.target.value)} onKeyDown={e=>e.key==="Enter"&&submit()}/>{error&&<p className="mt-2 text-sm text-danger">{error}</p>}<Button className="mt-4 w-full" onClick={submit} disabled={busy}>{busy?"Opening workspace…":"Continue"}<ArrowRight size={16}/></Button></div></Card></div>
  </main>;
}
