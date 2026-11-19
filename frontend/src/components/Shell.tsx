import * as Dialog from "@radix-ui/react-dialog";
import { BarChart3, Bell, BookOpen, Bot, ClipboardList, HelpCircle, Home, LogOut, Menu, MessageSquare, MessageSquareWarning, Plug, Settings2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { useAuth } from "../app/providers";
import { Button, Drawer } from "./ui";
import { ThemeControl } from "./ThemeControl";
import { useProtectedNavigation } from "./UnsavedChanges";
import { PersonalNotifications } from "../features/integrations/PersonalNotifications";
import { EmployeeHelp } from "../features/employee/EmployeeHelp";

export function Shell({ children, sidebar, eyebrow, title, headerContent }: {
  children: ReactNode; sidebar?: ReactNode; eyebrow: string; title?: string; headerContent?: ReactNode | ((openNavigation: () => void) => ReactNode);
}) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [mobile, setMobile] = useState(false);
  const [account, setAccount] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [help, setHelp] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const navigationOpener = useRef<HTMLElement | null>(null);
  const navigationSelected = useRef(false);
  const workspace = useRef<HTMLDivElement>(null);
  const header = useRef<HTMLElement>(null);
  const protect = useProtectedNavigation();
  const admin = user?.role === "knowledge_admin";
  const employee = user?.role === "employee";
  const requestedSection = new URLSearchParams(location.search).get("section") || "overview";
  const section = ["overview", "documents", "quality", "settings", "integrations"].includes(requestedSection) ? requestedSection : "overview";
  const chat = location.pathname === "/employee" || location.pathname === "/chat";
  const entries = admin ? [
    {to: "/knowledge?section=overview", label: "Overview", icon: BarChart3, active: !chat && section === "overview"},
    {to: "/knowledge?section=documents", label: "Documents", icon: BookOpen, active: !chat && section === "documents"},
    {to: "/knowledge?section=quality", label: "Answer quality", icon: MessageSquareWarning, active: !chat && section === "quality"},
    {to: "/knowledge?section=settings", label: "AI settings", icon: Settings2, active: !chat && section === "settings"},
    {to: "/knowledge?section=integrations", label: "Integrations", icon: Plug, active: !chat && section === "integrations"},
  ] : employee ? [
    {to: "/home", label: "Home", icon: Home, active: location.pathname === "/home"},
    {to: "/requests", label: "My requests", icon: ClipboardList, active: location.pathname === "/requests"},
    {to: "/employee", label: "My chats", icon: MessageSquare, active: chat},
  ] : [
    {to: "/manager", label: "Review queue", icon: ClipboardList, active: true},
  ];
  const pageTitle = title || entries.find(item => item.active)?.label || eyebrow;
  useEffect(() => { if (mobile) navigationSelected.current = true; setMobile(false); }, [location.pathname, location.search]);
  const openNavigation = () => {
    navigationOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    navigationSelected.current = false;
    setMobile(true);
  };
  useEffect(() => {
    const desktop = window.matchMedia?.("(min-width: 1024px)");
    const closeOnDesktop = () => { if (desktop?.matches) setMobile(false); };
    closeOnDesktop();
    desktop?.addEventListener("change", closeOnDesktop);
    return () => desktop?.removeEventListener("change", closeOnDesktop);
  }, []);
  useEffect(() => { document.title = `${pageTitle} · PeopleFlow AI`; }, [pageTitle]);
  useEffect(() => {
    if (!header.current || typeof ResizeObserver === "undefined") return;
    const measure = () => workspace.current?.style.setProperty("--workspace-header-height", `${header.current?.getBoundingClientRect().height ?? 64}px`);
    const observer = new ResizeObserver(measure);
    observer.observe(header.current);
    measure();
    return () => observer.disconnect();
  }, []);

  const connectionAction = !admin && <button onClick={() => { setMobile(false); setNotifications(true); }} aria-haspopup="dialog"
    className="workspace-nav-item focus-ring flex min-h-11 w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm font-medium text-muted hover:bg-raised hover:text-cream">
    <Bell size={18} aria-hidden="true"/>Personal notifications
  </button>;
  const navigation = <>
    <p className="mb-2 px-3 text-xs font-medium text-muted">{employee ? "Employee" : admin ? "Knowledge admin" : "Manager"} workspace</p>
    <nav aria-label="Main navigation" className="space-y-1">
      {entries.map(({to, label, icon: Icon, active}) => <Link key={to} to={to} aria-current={active ? "page" : undefined}
        className={`workspace-nav-item focus-ring flex min-h-11 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${active ? "bg-lime-soft text-lime" : "text-muted hover:bg-raised hover:text-cream"}`}>
        <Icon size={18} aria-hidden="true"/>{label}
      </Link>)}
    </nav>
    {sidebar && <div className="mt-5 border-t border-line pt-5">{sidebar}</div>}
  </>;
  const brand = <div className="flex items-center gap-3">
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent text-on-accent"><Bot size={20} aria-hidden="true"/></span>
    <div><strong className="block text-sm">PeopleFlow AI</strong><span className="text-xs text-muted">Your work, connected</span></div>
  </div>;

  return <div ref={workspace} className={`workspace-shell min-h-dvh lg:grid lg:grid-cols-[224px_minmax(0,1fr)] ${headerContent ? "has-header-search" : ""}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className="sticky top-0 hidden h-dvh min-w-0 flex-col border-r border-line bg-panel p-3 lg:flex">
      <div className="flex min-h-12 items-center px-2">{brand}</div>
      <div className="scrollbar mt-4 min-h-0 flex-1 overflow-y-auto">{navigation}</div>
      {connectionAction && <div className="mt-3 border-t border-line pt-3">{connectionAction}</div>}
    </aside>
    <Dialog.Root open={mobile} onOpenChange={setMobile}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-40 bg-black/45 lg:hidden"/>
        <Dialog.Content aria-describedby={undefined}
          onClick={event => {
            // Selecting the current section/chat does not change the URL, but
            // should still return the user from the drawer to that page.
            if (event.target instanceof Element && event.target.closest('[aria-current="page"]')) { navigationSelected.current = true; setMobile(false); }
          }}
          onCloseAutoFocus={event => {
          event.preventDefault();
          if (navigationSelected.current || window.matchMedia?.("(min-width: 1024px)").matches) document.getElementById("main-content")?.focus();
          else if (navigationOpener.current?.isConnected) navigationOpener.current.focus();
          else menuButton.current?.focus();
        }}
          className="navigation-drawer fixed inset-y-0 left-0 z-50 flex w-[min(320px,calc(100%_-_2rem))] flex-col border-r border-line bg-panel p-4 shadow-xl lg:hidden">
          <div className="flex items-center justify-between gap-2">{brand}<Dialog.Close asChild><Button tone="ghost" aria-label="Close menu" className="h-11 w-11 shrink-0 p-0"><X size={20}/></Button></Dialog.Close></div>
          <Dialog.Title className="sr-only">Workspace navigation</Dialog.Title>
          <div className="scrollbar mt-5 min-h-0 flex-1 overflow-y-auto">{navigation}</div>
          {connectionAction && <div className="mt-3 border-t border-line pt-3">{connectionAction}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
    <div className="min-w-0">
      <header ref={header} className="workspace-header sticky top-0 z-20 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-panel px-4 py-2 sm:px-6">
        <button ref={menuButton} aria-label="Open menu" aria-expanded={mobile} aria-haspopup="dialog" onClick={openNavigation}
          className="focus-ring grid h-11 w-11 shrink-0 place-items-center rounded-lg text-muted hover:bg-raised lg:hidden"><Menu size={21}/></button>
        <p className={`min-w-0 truncate text-sm font-semibold ${headerContent ? "flex-1 md:flex-none md:pr-3" : "flex-1"}`}>{pageTitle}</p>
        {headerContent && <div className="order-3 w-full min-w-0 pb-1 md:order-none md:mx-auto md:w-auto md:max-w-lg md:flex-1 md:pb-0">{typeof headerContent === "function" ? headerContent(openNavigation) : headerContent}</div>}
        {employee && <Button tone="ghost" className="ml-auto shrink-0 px-2" aria-label="Employee help" aria-haspopup="dialog" onClick={() => setHelp(true)}><HelpCircle size={19} aria-hidden="true"/><span className="hidden sm:inline">Help</span></Button>}
        <Button tone="ghost" className={`${employee ? "" : "ml-auto"} max-w-[40%] gap-2 px-2 md:max-w-[30%]`} aria-label="Account and appearance" aria-haspopup="dialog" onClick={() => setAccount(true)}>
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-raised text-xs text-cream" aria-hidden="true">{user?.display_name.split(" ").map(part => part[0]).slice(0, 2).join("")}</span>
          <span className="hidden truncate text-xs sm:block">{user?.display_name}</span>
        </Button>
      </header>
      <main id="main-content" tabIndex={-1} className="min-w-0 outline-none">{children}</main>
    </div>
    <Drawer open={account} onOpenChange={setAccount} title="Your account" description="Your role is assigned by the application." placement="center" size="small">
      <div className="space-y-6"><div><p className="font-semibold">{user?.display_name}</p><p className="mt-1 text-sm capitalize text-muted">{user?.role.replaceAll("_", " ")}</p></div>
        <ThemeControl/>
        <div className="border-t border-line pt-4"><Button tone="secondary" onClick={() => protect(() => { setAccount(false); logout(); })}><LogOut size={16}/>Sign out</Button></div>
      </div>
    </Drawer>
    {!admin && <PersonalNotifications open={notifications} onOpenChange={setNotifications} hideTrigger/>}
    {employee && <EmployeeHelp open={help} onOpenChange={setHelp}/>}
  </div>;
}
