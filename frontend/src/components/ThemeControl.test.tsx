import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { applyTheme, ThemeControl, ThemeSync } from "./ThemeControl";

let dark=false;
let listener: (()=>void) | undefined;
beforeEach(()=>{ localStorage.clear(); dark=false; vi.stubGlobal("matchMedia",()=>({matches:dark,addEventListener:(_type:string,fn:()=>void)=>{listener=fn;},removeEventListener:vi.fn()})); });
afterEach(()=>{cleanup(); vi.unstubAllGlobals(); delete document.documentElement.dataset.theme;});
it("persists the selected appearance and restores it on mount",()=>{
  const view=render(<ThemeControl/>);
  fireEvent.change(screen.getByLabelText("Appearance"),{target:{value:"dark"}});
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("pf_theme")).toBe("dark");
  view.unmount(); render(<ThemeControl/>);
  expect(screen.getByLabelText("Appearance")).toHaveValue("dark");
});
it("follows device appearance when no explicit preference is set",()=>{
  applyTheme(); expect(document.documentElement.dataset.theme).toBe("light");
  render(<ThemeSync/>); dark=true; listener?.();
  expect(document.documentElement.dataset.theme).toBe("dark");
  localStorage.setItem("pf_theme","light"); listener?.();
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("updates the appearance control when another tab changes the preference",()=>{
  render(<><ThemeSync/><ThemeControl/></>);
  localStorage.setItem("pf_theme","dark");
  fireEvent(window,new StorageEvent("storage",{key:"pf_theme",newValue:"dark"}));
  expect(screen.getByLabelText("Appearance")).toHaveValue("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  localStorage.removeItem("pf_theme");
  fireEvent(window,new StorageEvent("storage",{key:"pf_theme",newValue:null}));
  expect(screen.getByLabelText("Appearance")).toHaveValue("system");
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("keeps an explicit theme when reopening settings if saving the preference fails",()=>{
  const save = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage is unavailable"); });
  try {
    const view = render(<ThemeControl/>);
    fireEvent.change(screen.getByLabelText("Appearance"), {target:{value:"dark"}});
    expect(document.documentElement.dataset.theme).toBe("dark");
    view.unmount();
    render(<><ThemeSync/><ThemeControl/></>);
    expect(screen.getByLabelText("Appearance")).toHaveValue("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    listener?.();
    expect(document.documentElement.dataset.theme).toBe("dark");
  } finally {
    save.mockRestore();
    fireEvent.change(screen.getByLabelText("Appearance"), {target:{value:"light"}});
    fireEvent.change(screen.getByLabelText("Appearance"), {target:{value:"system"}});
  }
});
