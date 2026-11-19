import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import { clsx } from "clsx";
import { useRef, type ButtonHTMLAttributes, type ReactNode, type Ref } from "react";

export function Button({ className, tone = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "secondary" | "ghost" | "danger" }) {
  return <button type="button" className={clsx("workspace-button focus-ring inline-flex min-h-11 max-w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50",
    tone === "primary" && "bg-accent text-on-accent hover:brightness-95",
    tone === "secondary" && "border border-control bg-panel text-cream hover:bg-raised",
    tone === "ghost" && "text-muted hover:bg-raised hover:text-cream",
    tone === "danger" && "bg-danger/12 text-danger hover:bg-danger/20", className)} {...props} />;
}
export function Card({ children, className, padding = "normal" }: { children: ReactNode; className?: string; padding?: "normal" | "none" }) {
  return <div className={clsx("min-w-0 rounded-lg border border-line bg-panel", padding === "normal" && "p-4 sm:p-5", className)}>{children}</div>;
}
export function LoadingSkeleton({ label, rows = 3, className }: { label: string; rows?: number; className?: string }) {
  return <div role="status" aria-live="polite" aria-atomic="true" className={clsx("loading-skeleton", className)}>
    <p className="text-sm text-muted">{label}</p>
    <div aria-hidden="true" className="skeleton-list">{Array.from({ length: Math.max(1, Math.min(6, rows)) }, (_, index) => <div className="skeleton-row" key={index}><span/><span/></div>)}</div>
  </div>;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" }) {
  return <span className={clsx("inline-flex max-w-full items-center rounded-md border px-2 py-1 text-xs font-semibold leading-4",
    tone === "neutral" && "border-line bg-raised text-muted", tone === "success" && "border-lime/25 bg-lime-soft text-lime",
    tone === "warning" && "border-coral/25 bg-coral/10 text-coral", tone === "danger" && "border-danger/25 bg-danger/10 text-danger")}>{children}</span>;
}
export function Drawer({ open, onOpenChange, title, description, children, footer, placement = "side", size = "medium" }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description?: string; children: ReactNode; footer?: ReactNode; placement?: "side" | "center"; size?: "small" | "medium" | "large" }) {
  const opener = useRef<HTMLElement | null>(null);
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="dialog-overlay fixed inset-0 z-50 bg-black/45" />
    <Dialog.Content data-placement={placement} {...(!description ? {"aria-describedby": undefined} : {})}
      onOpenAutoFocus={() => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; }}
      onCloseAutoFocus={event => { event.preventDefault(); if (opener.current?.isConnected) opener.current.focus(); else document.getElementById("main-content")?.focus(); }}
      onFocusCapture={event => {
        // Radix wraps keyboard focus with preventScroll. Reveal the target when
        // short screens use one scrolling area for the entire dialog.
        const shortViewport = document.documentElement.dataset.viewportShort === "true" || window.matchMedia?.("(max-height: 540px)").matches;
        if (shortViewport && event.target instanceof HTMLElement && event.target !== event.currentTarget && event.currentTarget.contains(event.target)) {
          event.target.scrollIntoView?.({ block: "nearest" });
        }
      }}
      className={clsx(
      "dialog-content soft-shadow fixed z-50 flex min-h-0 flex-col overflow-hidden border border-line bg-panel",
      placement === "side" && "inset-y-0 right-0 w-full max-w-[560px] border-y-0 border-r-0",
      placement === "center" && "left-1/2 top-1/2 max-h-[calc(100dvh_-_2rem)] w-[calc(100%_-_2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl",
      placement === "center" && (size === "small" ? "max-w-[440px]" : size === "large" ? "max-w-[960px]" : "max-w-[680px]"),
    )}>
      <div className="dialog-header flex shrink-0 items-start justify-between gap-3 border-b border-line px-4 py-3 sm:px-6 sm:py-4"><div className="min-w-0 self-center [overflow-wrap:anywhere]"><Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>{description && <Dialog.Description className="mt-1 text-sm leading-5 text-muted">{description}</Dialog.Description>}</div>
      <Dialog.Close asChild><Button tone="ghost" aria-label="Close drawer" className="h-11 w-11 shrink-0" style={{ padding: 0 }}><X className="shrink-0" size={20}/></Button></Dialog.Close></div>
      <div className="dialog-body scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 [overflow-wrap:anywhere] sm:p-6">{children}</div>
      {footer && <div className="dialog-footer flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-line bg-panel px-4 py-3 sm:px-6">{footer}</div>}
    </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
export function PageHeader({ title, description, actions, children, headingRef }: { title: string; description?: string; actions?: ReactNode; children?: ReactNode; headingRef?: Ref<HTMLHeadingElement> }) {
  return <div className="page-heading"><div className="page-heading-row"><div className="min-w-0"><h1 ref={headingRef} tabIndex={-1} className="break-words text-2xl font-semibold tracking-tight outline-none">{title}</h1>{description && <p className="page-description">{description}</p>}</div>{actions && <div className="page-heading-actions">{actions}</div>}</div>{children}</div>;
}
export function ActionBar({ children, label = "Page actions" }: { children: ReactNode; label?: string }) {
  return <div role="group" aria-label={label} className="flex min-w-0 flex-wrap items-center gap-2">{children}</div>;
}
export function Hint({ label, children }: { label: string; children: ReactNode }) {
  return <Tooltip.Provider delayDuration={300}><Tooltip.Root><Tooltip.Trigger asChild>{children}</Tooltip.Trigger><Tooltip.Portal><Tooltip.Content sideOffset={8} className="z-[70] rounded-lg bg-cream px-2.5 py-1.5 text-xs text-ink">{label}</Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>;
}
export const fieldClass = "workspace-field focus-ring min-h-11 w-full min-w-0 rounded-md border border-control bg-panel px-3 py-2 text-sm text-cream placeholder:text-muted disabled:bg-raised disabled:text-muted";
export function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}
export function statusTone(status: string): "neutral" | "success" | "warning" | "danger" {
  if (["approved","completed","indexed"].includes(status)) return "success";
  if (["submitted","needs_information","in_review","indexing","draft","pending"].includes(status)) return "warning";
  if (["rejected","declined","cancelled","error"].includes(status)) return "danger";
  return "neutral";
}
