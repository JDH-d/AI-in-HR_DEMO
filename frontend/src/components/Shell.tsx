import { Bot, LogOut, Menu, Sparkles, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useAuth } from "../app/providers";
import { Button } from "./ui";

export function Shell({ children, sidebar, eyebrow }: { children: ReactNode; sidebar: ReactNode; eyebrow: string }) {
  const { user, logout } = useAuth(); const [mobile, setMobile] = useState(false);
  return <div className="min-h-screen lg:grid lg:grid-cols-[280px_1fr]">
    {mobile&&<button aria-label="Close navigation" className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={()=>setMobile(false)}/>}
    <aside className={`glass fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-line p-4 transition-transform lg:sticky lg:top-0 lg:h-screen ${mobile?"translate-x-0":"-translate-x-full lg:translate-x-0"}`}>
      <div className="flex h-14 items-center gap-3 px-2"><div className="grid h-9 w-9 place-items-center rounded-xl bg-lime text-ink"><Bot size={19}/></div><div><strong className="block text-sm">PeopleFlow AI</strong><span className="text-[11px] text-muted">Grounded people ops</span></div><Button tone="ghost" className="ml-auto h-9 w-9 px-0 lg:hidden" onClick={()=>setMobile(false)}><X size={17}/></Button></div>
      <div className="mt-5 flex-1 overflow-y-auto scrollbar">{sidebar}</div>
      <div className="mt-4 rounded-xl border border-line bg-ink/70 p-3"><div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-full bg-coral/15 text-coral"><Sparkles size={16}/></div><div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold">{user?.display_name}</p><p className="text-[10px] uppercase tracking-wider text-muted">{user?.role.replace("_"," ")}</p></div><button className="focus-ring rounded-lg p-2 text-muted hover:text-cream" onClick={logout} aria-label="Sign out"><LogOut size={16}/></button></div></div>
    </aside>
    <main className="min-w-0"><header className="glass sticky top-0 z-20 flex h-16 items-center border-b border-line px-4 lg:px-8"><button className="mr-3 text-muted lg:hidden" onClick={()=>setMobile(true)}><Menu/></button><span className="text-xs font-bold uppercase tracking-[.18em] text-muted">{eyebrow}</span></header>{children}</main>
  </div>;
}
