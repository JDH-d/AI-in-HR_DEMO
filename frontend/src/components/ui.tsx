import { X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({
  className,
  tone = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      className={clsx(
        "ui-button focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium disabled:pointer-events-none disabled:opacity-45",
        tone === "primary" && "ui-button-primary",
        tone === "secondary" && "ui-button-secondary text-cream",
        tone === "ghost" && "text-muted hover:bg-raised hover:text-cream",
        tone === "danger" && "bg-danger/12 text-danger hover:bg-danger/20",
        className,
      )}
      {...props}
    />
  );
}
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-line bg-panel",
        !className?.split(/\s+/).some((token) => /^p-/.test(token)) && "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center rounded-md border px-2 py-0.5 text-xs font-medium capitalize leading-5",
        tone === "neutral" && "border-line bg-raised text-muted",
        tone === "success" && "border-success/20 bg-success/10 text-success",
        tone === "warning" && "border-warning/20 bg-warning/10 text-warning",
        tone === "danger" && "border-danger/25 bg-danger/10 text-danger",
      )}
    >
      {children}
    </span>
  );
}
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  placement = "side",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  placement?: "side" | "center";
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-40" />
        <Dialog.Content
          className={clsx(
            "dialog-content scrollbar soft-shadow fixed z-50 w-full overflow-y-auto border border-line bg-ink p-6 sm:p-8",
            placement === "side" && "inset-y-0 right-0 max-w-[560px] border-y-0 border-r-0",
            placement === "center" &&
              "left-1/2 top-1/2 max-h-[calc(100dvh-2rem)] max-w-[min(760px,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl",
          )}
        >
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-xl font-semibold tracking-tight">{title}</Dialog.Title>
              {description && (
                <Dialog.Description className="mt-2 text-sm leading-6 text-muted">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <Button
                tone="ghost"
                aria-label="Close drawer"
                className="h-10 w-10"
                style={{ padding: 0 }}
              >
                <X className="shrink-0" size={20} />
              </Button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Hint({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={300}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={8}
            className="z-[70] rounded-lg bg-cream px-2.5 py-1.5 text-xs text-ink"
          >
            {label}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
export const fieldClass =
  "field w-full rounded-md border border-line bg-panel px-3.5 py-2.5 text-sm leading-6 text-cream placeholder:text-muted";
export function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}
export function statusTone(status: string): "neutral" | "success" | "warning" | "danger" {
  if (["approved", "acknowledged", "indexed"].includes(status)) return "success";
  if (["in_review", "reported", "indexing", "draft", "pending"].includes(status)) return "warning";
  if (["declined", "cancelled", "error"].includes(status)) return "danger";
  return "neutral";
}
