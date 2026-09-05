import { List, SignOut, X } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import { type ReactNode, useState } from "react";
import { useAuth } from "../app/providers";
import { BrandMark } from "./BrandMark";
import { ThemeToggle } from "./ThemeToggle";
import { Hint } from "./ui";

export function Shell({
  children,
  sidebar,
  eyebrow,
  onLogoClick,
  logoDisabled = false,
}: {
  children: ReactNode;
  sidebar: ReactNode;
  eyebrow: string;
  onLogoClick?: () => void;
  logoDisabled?: boolean;
}) {
  const { user, logout } = useAuth();
  const [mobile, setMobile] = useState(false);
  const HeaderTitle = onLogoClick ? "h1" : "span";
  const initials = (user?.display_name ?? "Demo Employee")
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
  const brand = (
    <>
      <BrandMark size={28} />
      <div className="min-w-0">
        <strong className="block text-[15px] font-medium">PeopleFlow AI</strong>
        <span className="mt-0.5 block text-xs text-muted">HR assistant</span>
      </div>
    </>
  );
  const navigation = (
    <>
      <div className="mb-7 flex h-12 items-center px-2">
        {onLogoClick ? (
          <button
            type="button"
            aria-label="Start a new chat"
            disabled={logoDisabled}
            onClick={() => {
              onLogoClick();
              setMobile(false);
            }}
            className="focus-ring flex min-w-0 flex-1 items-center gap-4 rounded-md p-1 text-left disabled:opacity-50"
          >
            {brand}
          </button>
        ) : (
          <div className="flex items-center gap-4 p-1">{brand}</div>
        )}
        <button
          type="button"
          className="icon-button ml-auto lg:hidden"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        >
          <X size={20} />
        </button>
      </div>
      {/* biome-ignore lint/a11y/noStaticElementInteractions lint/a11y/useKeyWithClickEvents: Delegates native button/link activation, including keyboard-generated clicks. */}
      <div
        className="scrollbar min-h-0 flex-1 overflow-y-auto"
        onClick={(event) => {
          if (
            mobile &&
            event.target instanceof Element &&
            event.target.closest("button, a") &&
            !event.target.closest("[data-keep-navigation]")
          )
            setMobile(false);
        }}
      >
        {sidebar}
      </div>
      <div className="mt-5 flex items-center gap-3 rounded-lg border border-line p-3">
        <div
          className="user-avatar grid h-9 w-9 shrink-0 place-items-center rounded-full text-xs font-medium"
          aria-hidden="true"
        >
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium">{user?.display_name}</p>
          <p className="mt-0.5 text-[11px] capitalize text-muted">
            {user?.role.replaceAll("_", " ")}
          </p>
        </div>
        <Hint label="Sign out">
          <button type="button" className="icon-button" onClick={logout} aria-label="Sign out">
            <SignOut size={18} />
          </button>
        </Hint>
      </div>
    </>
  );
  return (
    <Dialog.Root open={mobile} onOpenChange={setMobile}>
      <div className="shell">
        <a
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[80] focus:rounded-md focus:bg-accent focus:p-3 focus:text-on-accent"
          href="#workspace"
        >
          Skip to workspace
        </a>
        <aside className="shell-sidebar hidden lg:flex" aria-label="Workspace navigation">
          {navigation}
        </aside>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay fixed inset-0 z-30 lg:hidden" />
          <Dialog.Content
            className="shell-sidebar lg:hidden"
            data-open="true"
            aria-describedby={undefined}
          >
            <Dialog.Title className="sr-only">Workspace navigation</Dialog.Title>
            {navigation}
          </Dialog.Content>
        </Dialog.Portal>
        <main id="workspace" className="min-w-0" tabIndex={-1}>
          <header className="shell-header">
            <div className="flex min-w-0 items-center gap-3">
              <Dialog.Trigger asChild>
                <button
                  type="button"
                  aria-label="Open navigation"
                  className="icon-button lg:hidden"
                >
                  <List size={22} />
                </button>
              </Dialog.Trigger>
              <HeaderTitle className="truncate text-[15px] font-medium" title={eyebrow}>
                {eyebrow}
              </HeaderTitle>
            </div>
            <ThemeToggle />
          </header>
          {children}
        </main>
      </div>
    </Dialog.Root>
  );
}
