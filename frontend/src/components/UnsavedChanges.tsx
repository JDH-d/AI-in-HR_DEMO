import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { UNSAFE_DataRouterContext, useBlocker } from "react-router";
import { Button, Drawer } from "./ui";

type ProtectedAction = () => void | Promise<void>;
type Protection = { register: (id: string, dirty: boolean) => void; requestLeave: (action: ProtectedAction) => void };
const Context = createContext<Protection | null>(null);

/** One blocker for the application: forms register their unsaved state here. */
export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const forms = useRef(new Set<string>());
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<ProtectedAction | null>(null);
  const confirmedAction = useRef(false);
  const dataRouter = useContext(UNSAFE_DataRouterContext);
  const register = useCallback((id: string, changed: boolean) => {
    if (changed) forms.current.add(id); else forms.current.delete(id);
    setDirty(forms.current.size > 0);
  }, []);
  const isDirty = useCallback(() => !confirmedAction.current && forms.current.size > 0, []);
  const requestLeave = useCallback((action: ProtectedAction) => {
    if (forms.current.size) setPending(() => action); else action();
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return <Context.Provider value={{register, requestLeave}}>
    {children}
    {dataRouter && <RouteProtection isDirty={isDirty}/>}
    <LeaveDialog open={Boolean(pending)} cancel={() => setPending(null)} leave={() => {
      const action = pending;
      setPending(null);
      // Permit the action's own navigation without unregistering other forms.
      // If an asynchronous action fails, their visible text stays protected.
      confirmedAction.current = true;
      const finish = () => { confirmedAction.current = false; };
      try {
        const result = action?.();
        if (result) void result.then(finish, finish);
        else finish();
      } catch { finish(); }
    }}/>
  </Context.Provider>;
}

export function useUnsavedChanges(dirty: boolean) {
  const context = useContext(Context);
  const id = useId();
  const register = context?.register;
  useEffect(() => {
    register?.(id, dirty);
    return () => register?.(id, false);
  }, [register, id, dirty]);
  return useCallback((changed = false) => register?.(id, changed), [register, id]);
}

export function useProtectedNavigation() {
  const context = useContext(Context);
  return context?.requestLeave ?? ((action: ProtectedAction) => action());
}

function RouteProtection({isDirty}: {isDirty: () => boolean}) {
  const blocker = useBlocker(({currentLocation, nextLocation}) => isDirty() &&
    (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search));
  return <LeaveDialog open={blocker.state === "blocked"}
    cancel={() => blocker.state === "blocked" && blocker.reset()}
    leave={() => blocker.state === "blocked" && blocker.proceed()}/>;
}

function LeaveDialog({open, cancel, leave}: {open: boolean; cancel: () => void; leave: () => void}) {
  return <Drawer open={open} onOpenChange={value => { if (!value) cancel(); }} placement="center"
    title="Leave without saving?" description="Your unsaved changes will be discarded. Saved requests, messages and settings will stay unchanged." size="small" footer={<>
      <Button tone="secondary" onClick={cancel}>Keep editing</Button>
      <Button tone="danger" onClick={leave}>Discard changes and leave</Button>
    </>}>
    <p className="text-sm text-muted">Keep editing to finish or save your changes first.</p>
  </Drawer>;
}
